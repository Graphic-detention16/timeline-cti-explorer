from __future__ import annotations

import pytest

from timeline_cti.x_client import XApiError, XClient


def test_oauth_scope_validation_is_fail_closed() -> None:
    XClient._validate_scopes({"scope": "tweet.read users.read offline.access"})
    with pytest.raises(XApiError, match="required scopes"):
        XClient._validate_scopes({"scope": "tweet.read users.read"})
