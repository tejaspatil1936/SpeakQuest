"""``speakquest-local``: run the API, storage and workflow on one machine.

    speakquest-local seed            # pre-analyse reference takes into .local/
    speakquest-local serve           # http://localhost:8787

The server answers the same routes as API Gateway by calling the same
handler functions, serves ``/_storage/<key>`` with signature checks that
mirror S3 presigned URLs, and runs analyses through
:class:`~speakquest_api.local.runner.LocalWorkflow`. Coaching uses Bedrock
when AWS credentials are present in the environment, else the template.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse

from speakquest.logs import get_logger, log_event
from speakquest.storage import LocalStorage
from speakquest.timing import get_aligner
from speakquest_api.config import Settings, load_settings
from speakquest_api.handlers import Deps, dispatch
from speakquest_api.http import Request, cors_headers
from speakquest_api.local.runner import LocalWorkflow
from speakquest_api.repository import SqliteRepository
from speakquest_api.steps import StepDeps

log = get_logger("speakquest.local")
ROOT = Path(__file__).resolve().parents[4]
MAX_UPLOAD = 10 * 1024 * 1024 + 1024


def _secret(base: Path) -> bytes:
    path = base / "signing.key"
    if not path.exists():
        base.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return bytes.fromhex(path.read_text().strip())


def build(cfg: Settings, model: Any = None) -> tuple[Deps, LocalWorkflow, LocalStorage]:
    base = Path(cfg.local_dir).resolve()
    storage = LocalStorage(base / "bucket", cfg.local_base_url, _secret(base))
    repo = SqliteRepository(base / "speakquest.sqlite")
    workflow = LocalWorkflow(
        StepDeps(storage=storage, repo=repo, model=model), get_aligner(cfg.local_aligner)
    )
    return Deps(settings=cfg, storage=storage, repo=repo, workflow=workflow), workflow, storage


def _model_from_env() -> Any:
    if os.environ.get("SPEAKQUEST_BEDROCK", "1") == "0" or not (
        os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE")
    ):
        return None
    from speakquest_explain.coach import client_from_env  # noqa: PLC0415

    return client_from_env()


def make_handler(deps: Deps, storage: LocalStorage) -> type[BaseHTTPRequestHandler]:
    allowed = (*deps.settings.allowed_origins, "http://127.0.0.1:5173", "http://localhost:4173")

    class Handler(BaseHTTPRequestHandler):
        server_version = "speakquest-local"

        def log_message(self, fmt: str, *args: Any) -> None:
            log_event(log, "http", line=fmt % args)

        def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
            self.send_response(status)
            for k, v in {**headers, **cors_headers(self.headers.get("origin"), allowed)}.items():
                self.send_header(k, v)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(status, json.dumps(payload).encode(), {"content-type": "application/json"})

        def do_OPTIONS(self) -> None:
            self._send(204, b"", {"allow": "GET,POST,PUT,OPTIONS"})

        def _storage(self, method: str) -> None:
            url = urlparse(self.path)
            key = unquote(url.path[len("/_storage/") :])
            query = dict(parse_qsl(url.query))
            length = int(self.headers.get("content-length") or 0)
            ctype = self.headers.get("content-type", "")
            if not storage.verify(method, key, query, ctype, length if method == "PUT" else None):
                self._json(403, {"error": {"code": "SIGNATURE", "message": "Bad or expired URL."}})
                return
            if method == "PUT":
                if length > MAX_UPLOAD:
                    self._json(413, {"error": {"code": "TOO_LARGE", "message": "Too large."}})
                    return
                storage.put_bytes(key, self.rfile.read(length), ctype)
                self._send(200, b"", {"etag": '"local"'})
                return
            try:
                data = storage.get_bytes(key)
            except KeyError:
                self._json(404, {"error": {"code": "NoSuchKey", "message": key}})
                return
            ctype = mimetypes.guess_type(key)[0] or "application/octet-stream"
            if key.endswith(".json"):
                ctype = "application/json"
            self._send(200, data, {"content-type": ctype, "cache-control": "private, max-age=60"})

        def _api(self) -> None:
            url = urlparse(self.path)
            length = int(self.headers.get("content-length") or 0)
            req = Request(
                method=self.command,
                path=url.path,
                headers={k.lower(): v for k, v in self.headers.items()},
                query=dict(parse_qsl(url.query)),
                body=self.rfile.read(length) if length else b"",
                source_ip=self.client_address[0],
            )
            resp = dispatch(req, deps)
            self._send(resp["statusCode"], resp["body"].encode(), resp["headers"])

        def do_GET(self) -> None:
            if self.path.startswith("/_storage/"):
                self._storage("GET")
            elif self.path == "/healthz":
                self._json(200, {"ok": True})
            else:
                self._api()

        do_HEAD = do_GET  # noqa: N815

        def do_PUT(self) -> None:
            if self.path.startswith("/_storage/"):
                self._storage("PUT")
            else:
                self._json(405, {"error": {"code": "METHOD_NOT_ALLOWED", "message": "PUT"}})

        def do_POST(self) -> None:
            self._api()

    return Handler


def serve(cfg: Settings, host: str, port: int) -> None:
    deps, workflow, storage = build(cfg, _model_from_env())
    if not deps.repo.list_challenges():
        print("No challenges seeded yet — run `speakquest-local seed` first.", file=sys.stderr)
    httpd = ThreadingHTTPServer((host, port), make_handler(deps, storage))
    print(
        f"speakquest-local listening on http://{host}:{port} "
        f"(data in {Path(cfg.local_dir).resolve()}, aligner {cfg.local_aligner}, "
        f"coaching {'bedrock' if workflow.deps.model else 'template'})"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        workflow.shutdown()
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speakquest-local")
    sub = parser.add_subparsers(dest="cmd", required=True)
    srv = sub.add_parser("serve")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8787)
    sd = sub.add_parser("seed")
    sd.add_argument("--audio-dir", default=str(ROOT / "data" / "audio"))
    sd.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args(argv)

    env = dict(os.environ)
    env.setdefault("SPEAKQUEST_BACKEND", "local")
    if args.cmd == "serve":
        env.setdefault("SPEAKQUEST_LOCAL_BASE_URL", f"http://localhost:{args.port}")
    cfg = load_settings(env)
    if args.cmd == "serve":
        serve(cfg, args.host, args.port)
        return 0
    from speakquest_api.seed import seed  # noqa: PLC0415

    deps, workflow, storage = build(cfg)
    done = seed(storage, deps.repo, workflow.aligner, Path(args.audio_dir), args.only)
    workflow.shutdown()
    print(f"seeded {len(done)} challenges: {', '.join(done)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
