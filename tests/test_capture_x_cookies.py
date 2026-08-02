from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_capture_module() -> ModuleType:
    path = Path(__file__).parents[1] / "host_files" / "capture_x_cookies.py"
    spec = importlib.util.spec_from_file_location("capture_x_cookies", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_filter_x_cookies_keeps_only_x_domains() -> None:
    capture = load_capture_module()
    cookies = capture.filter_x_cookies(
        [
            {"name": "auth_token", "value": "a", "domain": ".x.com"},
            {"name": "ct0", "value": "b", "domain": "x.com"},
            {"name": "other", "value": "c", "domain": ".example.com"},
            {"name": "lookalike", "value": "d", "domain": "evilx.com"},
        ]
    )
    assert capture.cookie_names(cookies) == {"auth_token", "ct0"}
