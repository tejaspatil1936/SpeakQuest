"""Object storage: S3 in the cloud, a directory on disk locally.

Every Lambda and the local runner go through :class:`Storage`, so the same
handler code runs against either. Keys follow the bucket layout in system
design §7 (``uploads/``, ``work/``, ``transcripts/``, ``results/``,
``references/``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlencode


class Storage(Protocol):
    def get_bytes(self, key: str) -> bytes: ...
    def put_bytes(self, key: str, data: bytes, content_type: str = ...) -> None: ...
    def exists(self, key: str) -> bool: ...
    def download(self, key: str, dest: Path) -> Path: ...
    def upload(self, src: Path, key: str, content_type: str = ...) -> None: ...
    def presign_put(
        self, key: str, content_type: str, expires: int, content_length: int | None = None
    ) -> str: ...
    def presign_get(self, key: str, expires: int) -> str: ...
    def size(self, key: str) -> int | None: ...


def get_json(storage: Storage, key: str) -> Any:
    return json.loads(storage.get_bytes(key))


def put_json(storage: Storage, key: str, value: Any) -> None:
    storage.put_bytes(key, json.dumps(value, separators=(",", ":")).encode(), "application/json")


class StorageMissingError(KeyError):
    pass


# --------------------------------------------------------------------------- S3


class S3Storage:
    def __init__(self, bucket: str, client: Any | None = None, region: str | None = None):
        import boto3  # noqa: PLC0415 - not needed by local-only users
        from botocore.config import Config  # noqa: PLC0415

        self.bucket = bucket
        self.client = client or boto3.client(
            "s3",
            region_name=region or os.environ.get("AWS_REGION"),
            config=Config(
                signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}
            ),
        )

    def get_bytes(self, key: str) -> bytes:
        try:
            return bytes(self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read())
        except self.client.exceptions.NoSuchKey as exc:
            raise StorageMissingError(key) from exc

    def put_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def exists(self, key: str) -> bool:
        return self.size(key) is not None

    def size(self, key: str) -> int | None:
        from botocore.exceptions import ClientError  # noqa: PLC0415

        try:
            return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def download(self, key: str, dest: Path) -> Path:
        from botocore.exceptions import ClientError  # noqa: PLC0415

        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.download_file(self.bucket, key, str(dest))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise StorageMissingError(key) from exc
            raise
        return dest

    def upload(self, src: Path, key: str, content_type: str = "application/octet-stream") -> None:
        self.client.upload_file(str(src), self.bucket, key, ExtraArgs={"ContentType": content_type})

    def presign_put(
        self, key: str, content_type: str, expires: int, content_length: int | None = None
    ) -> str:
        # Content-Type and Content-Length are signed headers: S3 rejects a PUT
        # whose type or size differs from what POST /uploads validated.
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key, "ContentType": content_type}
        if content_length is not None:
            params["ContentLength"] = content_length
        return str(
            self.client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=expires,
                HttpMethod="PUT",
            )
        )

    def presign_get(self, key: str, expires: int) -> str:
        return str(
            self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires,
            )
        )


# --------------------------------------------------------------------------- local


class LocalStorage:
    """A directory that behaves like the bucket, with HMAC-signed URLs.

    The local API server (``speakquest-local``) serves ``/_storage/<key>``
    and verifies the signature, expiry and (for PUT) the content type, the
    same constraints an S3 presigned URL enforces.
    """

    def __init__(self, root: Path, base_url: str, secret: bytes):
        self.root = root.resolve()
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root) + os.sep):
            raise ValueError(f"key escapes storage root: {key}")
        return p

    def get_bytes(self, key: str) -> bytes:
        p = self.path(key)
        if not p.is_file():
            raise StorageMissingError(key)
        return p.read_bytes()

    def put_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def size(self, key: str) -> int | None:
        p = self.path(key)
        return p.stat().st_size if p.is_file() else None

    def download(self, key: str, dest: Path) -> Path:
        src = self.path(key)
        if not src.is_file():
            raise StorageMissingError(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return dest

    def upload(self, src: Path, key: str, content_type: str = "application/octet-stream") -> None:
        self.put_bytes(key, src.read_bytes(), content_type)

    def _sign(self, method: str, key: str, expires_at: int, content_type: str, length: str) -> str:
        msg = f"{method}\n{key}\n{expires_at}\n{content_type}\n{length}".encode()
        digest = hmac.new(self.secret, msg, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def _url(
        self, method: str, key: str, expires: int, content_type: str = "", length: int | None = None
    ) -> str:
        expires_at = int(time.time()) + expires
        size = "" if length is None else str(length)
        query: dict[str, str | int] = {
            "m": method,
            "e": expires_at,
            "s": self._sign(method, key, expires_at, content_type, size),
        }
        if content_type:
            query["ct"] = content_type
        if size:
            query["len"] = size
        return f"{self.base_url}/_storage/{quote(key)}?{urlencode(query)}"

    def presign_put(
        self, key: str, content_type: str, expires: int, content_length: int | None = None
    ) -> str:
        return self._url("PUT", key, expires, content_type, content_length)

    def presign_get(self, key: str, expires: int) -> str:
        return self._url("GET", key, expires)

    def verify(
        self,
        method: str,
        key: str,
        query: dict[str, str],
        content_type: str = "",
        content_length: int | None = None,
    ) -> bool:
        """Check a signed URL the way S3 would: method, expiry, signature and,
        for uploads, the exact Content-Type and Content-Length that were signed."""
        try:
            expires_at = int(query["e"])
        except (KeyError, ValueError):
            return False
        if query.get("m") != method or expires_at < time.time():
            return False
        signed_ct = query.get("ct", "")
        signed_len = query.get("len", "")
        if method == "PUT" and signed_ct != content_type:
            return False
        if method == "PUT" and signed_len and signed_len != str(content_length):
            return False
        expected = self._sign(method, key, expires_at, signed_ct, signed_len)
        return hmac.compare_digest(expected, query.get("s", ""))
