from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("SPEAKQUEST_LIVE_AWS") == "1":
        return
    skip = pytest.mark.skip(reason="live AWS test; set SPEAKQUEST_LIVE_AWS=1 to run")
    for item in items:
        if "live_aws" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def repo_root() -> Path:
    return ROOT
