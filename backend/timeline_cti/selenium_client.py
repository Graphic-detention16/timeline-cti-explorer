from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver import ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from .config import Settings
from .selenium_extraction import EXTRACT_TWEETS_JS, build_author, build_post, extract_post_id

TAB_LABELS: dict[str, tuple[str, ...]] = {
    "following": ("Following", "Takip edilenler"),
    "for_you": ("For you", "Sana özel"),
}
LOGIN_URL_MARKERS = ("/i/flow/login", "/login")
CHALLENGE_URL_MARKERS = ("/account/access", "/challenge", "arkose")


class SeleniumSessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserFingerprint:
    width: int
    height: int
    locale: str
    timezone: str


class HumanPacer:
    def __init__(self, rng: random.SystemRandom | None = None) -> None:
        self._rng = rng or random.SystemRandom()

    def dwell_seconds(self) -> float:
        base = self._rng.lognormvariate(1.4, 0.45)
        if self._rng.random() < 0.08:  # noqa: S311  # nosec B311
            base += self._rng.uniform(8.0, 20.0)  # noqa: S311  # nosec B311
        return min(max(base, 1.2), 18.0)

    def scroll_delta(self, viewport_height: int) -> int:
        fraction = self._rng.uniform(0.28, 0.72)  # noqa: S311  # nosec B311
        return max(180, int(viewport_height * fraction))

    def should_scroll_back(self) -> bool:
        return self._rng.random() < 0.12  # noqa: S311  # nosec B311

    def idle_jitter(self, maximum: int) -> int:
        if maximum <= 0:
            return 0
        return self._rng.randint(0, maximum)  # noqa: S311  # nosec B311


def build_fingerprint(
    settings: Settings, rng: random.SystemRandom | None = None
) -> BrowserFingerprint:
    randomizer = rng or random.SystemRandom()
    width = randomizer.choice([1366, 1440, 1536, 1600, 1920])  # noqa: S311  # nosec B311
    height = randomizer.choice([768, 900, 960, 1080])  # noqa: S311  # nosec B311
    return BrowserFingerprint(
        width=width,
        height=height,
        locale=settings.SELENIUM_LOCALE,
        timezone=settings.SELENIUM_TIMEZONE,
    )


def create_remote_driver(settings: Settings, fingerprint: BrowserFingerprint) -> WebDriver:
    options = ChromeOptions()
    options.add_argument(f"--window-size={fingerprint.width},{fingerprint.height}")
    options.add_argument(f"--lang={fingerprint.locale}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Remote(command_executor=settings.SELENIUM_REMOTE_URL, options=options)
    driver.set_window_size(fingerprint.width, fingerprint.height)
    return driver


def load_session(driver: WebDriver, cookies: list[dict[str, Any]]) -> None:
    driver.get("https://x.com")
    time.sleep(1.5)
    for cookie in cookies:
        payload: dict[str, Any] = {
            "name": str(cookie.get("name", "")),
            "value": str(cookie.get("value", "")),
        }
        if not payload["name"]:
            continue
        domain = str(cookie.get("domain", ".x.com"))
        payload["domain"] = domain
        if path := cookie.get("path"):
            payload["path"] = str(path)
        if secure := cookie.get("secure"):
            payload["secure"] = bool(secure)
        try:
            driver.add_cookie(payload)
        except WebDriverException:
            continue
    driver.get("https://x.com/home")
    time.sleep(2.0)


def session_problem(driver: WebDriver) -> str | None:
    current_url = driver.current_url.lower()
    if any(marker in current_url for marker in CHALLENGE_URL_MARKERS):
        return (
            "X verification challenge detected; complete it in normal Chrome, "
            "then recapture and import the session"
        )
    if any(marker in current_url for marker in LOGIN_URL_MARKERS):
        return "browser session expired; recapture and import the session"
    return None


def ensure_session_ready(driver: WebDriver, timeout: int = 20) -> None:
    if problem := session_problem(driver):
        raise SeleniumSessionError(problem)
    try:
        WebDriverWait(driver, timeout).until(
            ec.presence_of_element_located(
                (By.CSS_SELECTOR, '[data-testid="SideNav_AccountSwitcher_Button"]')
            )
        )
    except WebDriverException as exc:
        if problem := session_problem(driver):
            raise SeleniumSessionError(problem) from exc
        raise SeleniumSessionError(
            "X home timeline did not become ready; refresh the manually captured session"
        ) from exc


def select_tab(driver: WebDriver, tab: str) -> None:
    labels = TAB_LABELS.get(tab, TAB_LABELS["following"])
    for label in labels:
        try:
            element = driver.find_element(
                By.XPATH,
                "//*[@role='tab' or self::a]"
                f"[.//span[normalize-space()='{label}'] or normalize-space()='{label}']",
            )
            driver.execute_script("arguments[0].click();", element)
            time.sleep(2.0)
            return
        except WebDriverException:
            continue
    raise SeleniumSessionError(f"unable to locate timeline tab {tab}")


def extract_visible_posts(driver: WebDriver) -> list[dict[str, Any]]:
    raw_items = driver.execute_script(EXTRACT_TWEETS_JS)
    if not isinstance(raw_items, list):
        return []
    prepared: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        post = build_post(raw)
        if post is None:
            continue
        prepared.append(
            {"post": post, "author": build_author(raw), "_raw_id": extract_post_id(raw)}
        )
    return prepared


def human_scroll_once(
    driver: WebDriver,
    pacer: HumanPacer,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    viewport = driver.execute_script(
        "return {height: window.innerHeight || document.documentElement.clientHeight, "
        "scrollY: window.pageYOffset || document.documentElement.scrollTop};"
    )
    if not isinstance(viewport, dict):
        return
    height = int(viewport.get("height", 900))
    scroll_y = int(viewport.get("scrollY", 0))
    delta = pacer.scroll_delta(height)
    if pacer.should_scroll_back():
        delta = -max(120, delta // 3)
    driver.execute_script("window.scrollTo(0, arguments[0]);", max(0, scroll_y + delta))
    sleep_fn(pacer.dwell_seconds())
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        ActionChains(driver).move_to_element_with_offset(
            body,
            pacer._rng.randint(40, 240),  # noqa: S311  # nosec B311
            pacer._rng.randint(80, 420),  # noqa: S311  # nosec B311
        ).perform()
    except WebDriverException:
        return


def crawl_timeline(
    driver: WebDriver,
    *,
    tab: str,
    scroll_seconds: int,
    budget: int,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[dict[str, Any]]:
    select_tab(driver, tab)
    pacer = HumanPacer()
    deadline = monotonic() + scroll_seconds
    collected: dict[str, dict[str, Any]] = {}
    stagnant_rounds = 0
    last_count = -1

    while monotonic() < deadline and len(collected) < budget:
        if problem := session_problem(driver):
            raise SeleniumSessionError(problem)
        for item in extract_visible_posts(driver):
            post_id = str(item.get("_raw_id", ""))
            if not post_id:
                continue
            collected[post_id] = item
            if len(collected) >= budget:
                break
        if len(collected) >= budget:
            break
        if len(collected) == last_count:
            stagnant_rounds += 1
            if stagnant_rounds >= 4:
                break
        else:
            stagnant_rounds = 0
        last_count = len(collected)
        human_scroll_once(driver, pacer, sleep_fn=sleep_fn)

    return list(collected.values())[:budget]


def next_tab(last_tab: str) -> str:
    return "for_you" if last_tab == "following" else "following"
