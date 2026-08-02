from __future__ import annotations

import random

from timeline_cti.selenium_client import HumanPacer, next_tab, session_problem


def test_human_pacer_bounds() -> None:
    pacer = HumanPacer(random.SystemRandom())
    for _ in range(50):
        dwell = pacer.dwell_seconds()
        assert 1.2 <= dwell <= 18.0
        delta = pacer.scroll_delta(900)
        assert 180 <= delta <= 900


def test_next_tab_alternates() -> None:
    assert next_tab("following") == "for_you"
    assert next_tab("for_you") == "following"


class FakeDriver:
    def __init__(self, url: str) -> None:
        self.current_url = url


def test_session_problem_distinguishes_login_and_challenge() -> None:
    assert "expired" in str(session_problem(FakeDriver("https://x.com/i/flow/login")))  # type: ignore[arg-type]
    assert "challenge" in str(session_problem(FakeDriver("https://x.com/account/access")))  # type: ignore[arg-type]
    assert session_problem(FakeDriver("https://x.com/home")) is None  # type: ignore[arg-type]
