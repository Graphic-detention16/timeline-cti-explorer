#!/usr/bin/env python3
"""Yerel Chrome ile X'e giriş yapıp cookie'leri host_files altına kaydeder.

Kullanım:
    python host_files/capture_x_cookies.py
    python host_files/capture_x_cookies.py --import-docker

Gereksinimler:
    pip install selenium
    Google Chrome veya Chromium (Selenium 4.6+ sürücüyü otomatik indirir)

Çıktı:
    host_files/x_cookies.json  (Git'e girmez)

Docker collector'a aktarmak için:
    python host_files/capture_x_cookies.py --import-docker
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REQUIRED_COOKIE_NAMES = frozenset({"auth_token", "ct0"})
LOGIN_URL = "https://x.com/i/flow/login"
HOME_URL = "https://x.com/home"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "x_cookies.json"
DEFAULT_PROFILE = SCRIPT_DIR / "chrome-profile"
X_COOKIE_DOMAINS = ("x.com", "twitter.com")


def _require_selenium() -> Any:
    try:
        from selenium import webdriver
        from selenium.webdriver import ChromeOptions
    except ImportError as exc:
        raise SystemExit(
            "selenium paketi gerekli. Kurulum: pip install selenium"
        ) from exc
    return webdriver, ChromeOptions


def normalize_cookie(cookie: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "name": str(cookie["name"]),
        "value": str(cookie["value"]),
    }
    if domain := cookie.get("domain"):
        normalized["domain"] = str(domain)
    if path := cookie.get("path"):
        normalized["path"] = str(path)
    if "secure" in cookie:
        normalized["secure"] = bool(cookie["secure"])
    if expiry := cookie.get("expiry"):
        normalized["expiry"] = int(expiry)
    return normalized


def filter_x_cookies(raw_cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in raw_cookies:
        domain = str(item.get("domain", "")).lower().lstrip(".")
        is_x_cookie = any(
            domain == suffix or domain.endswith(f".{suffix}")
            for suffix in X_COOKIE_DOMAINS
        )
        if not is_x_cookie:
            continue
        selected.append(normalize_cookie(item))
    return selected


def cookie_names(cookies: list[dict[str, Any]]) -> set[str]:
    return {str(cookie["name"]) for cookie in cookies}


def find_chrome_binary(explicit: Path | None = None) -> str:
    if explicit is not None:
        if explicit.is_file():
            return str(explicit)
        raise RuntimeError(f"Chrome binary bulunamadı: {explicit}")
    for candidate in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        if binary := shutil.which(candidate):
            return binary
    raise RuntimeError(
        "Google Chrome veya Chromium bulunamadı. --chrome-binary ile yolu belirtin."
    )


def available_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def launch_manual_browser(
    chrome_binary: str,
    *,
    profile_dir: Path,
    debug_port: int,
) -> subprocess.Popen[bytes]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        chrome_binary,
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={profile_dir.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        LOGIN_URL,
    ]
    return subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def devtools_pages(debug_port: int) -> list[dict[str, Any]]:
    url = f"http://127.0.0.1:{debug_port}/json"
    try:
        with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def wait_for_manual_login(
    debug_port: int,
    *,
    timeout: int,
    browser_process: subprocess.Popen[bytes],
) -> None:
    deadline = time.monotonic() + timeout
    stable_home_polls = 0
    print(
        "Açılan normal Chrome penceresinde X'e elle giriş yapın. "
        "Ana sayfa açılınca sistem otomatik algılayacak…",
        flush=True,
    )
    while time.monotonic() < deadline:
        if browser_process.poll() is not None:
            raise RuntimeError("Chrome giriş tamamlanmadan kapandı")
        home_visible = False
        for page in devtools_pages(debug_port):
            page_url = str(page.get("url", "")).lower()
            if page_url.startswith(("https://x.com/home", "https://twitter.com/home")):
                home_visible = True
                break
        stable_home_polls = stable_home_polls + 1 if home_visible else 0
        if stable_home_polls >= 3:
            return
        time.sleep(1)
    raise TimeoutError(
        f"{timeout} saniye içinde X ana sayfası algılanamadı. "
        "Doğrulama varsa elle tamamlayıp /home sayfasına geçin."
    )


def attach_after_login(debug_port: int) -> Any:
    webdriver, ChromeOptions = _require_selenium()
    options = ChromeOptions()
    options.debugger_address = f"127.0.0.1:{debug_port}"
    return webdriver.Chrome(options=options)


def wait_for_required_cookies(driver: Any, timeout: int = 20) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cookies = filter_x_cookies(driver.get_cookies())
        if cookie_names(cookies) >= REQUIRED_COOKIE_NAMES:
            return cookies
        time.sleep(1)
    raise RuntimeError(
        "X ana sayfası açıldı ancak auth_token / ct0 oluşmadı. "
        "Hesap menüsünün göründüğünü doğrulayıp tekrar deneyin."
    )


def save_cookies(cookies: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")
    with contextlib.suppress(OSError):
        output.chmod(0o600)


def import_via_docker(cookie_path: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker komutu bulunamadı")
    probe = subprocess.run(  # noqa: S603
        [docker, "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    prefix = [docker]
    if probe.returncode != 0:
        sudo = shutil.which("sudo")
        if sudo is None:
            raise RuntimeError(
                "Docker socket erişimi yok ve sudo bulunamadı; "
                "kullanıcıyı docker grubuna ekleyin veya import komutunu sudo ile çalıştırın"
            )
        print("Docker socket erişimi için sudo kullanılacak.", flush=True)
        prefix = [sudo, docker]
    command = [
        *prefix,
        "compose",
        "exec",
        "-T",
        "collector",
        "timeline-cti-cli",
        "import-cookies",
        "-",
    ]
    subprocess.run(  # noqa: S603
        command,
        input=cookie_path.read_bytes(),
        check=True,
        cwd=SCRIPT_DIR.parent,
    )


def import_via_local_package(cookie_path: Path) -> None:
    from timeline_cti.cli import import_cookies

    count = import_cookies(cookie_path)
    print(f"Yerel state store'a {count} cookie aktarıldı.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="X oturum cookie yakalayıcı")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Çıktı dosyası (varsayılan: {DEFAULT_OUTPUT.name})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Giriş bekleme süresi (saniye)",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE,
        help=f"Kalıcı Chrome profil dizini (varsayılan: {DEFAULT_PROFILE})",
    )
    parser.add_argument(
        "--chrome-binary",
        type=Path,
        default=None,
        help="Chrome/Chromium binary yolu (normalde otomatik bulunur)",
    )
    parser.add_argument(
        "--import-docker",
        action="store_true",
        help="Kayıttan sonra collector konteynerine şifreli aktarım yap",
    )
    parser.add_argument(
        "--import-local",
        action="store_true",
        help="Kayıttan sonra yerel .env / state store'a aktar (paket kurulu olmalı)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    driver = None
    browser_process: subprocess.Popen[bytes] | None = None
    try:
        chrome_binary = find_chrome_binary(args.chrome_binary)
        debug_port = available_local_port()
        browser_process = launch_manual_browser(
            chrome_binary,
            profile_dir=args.profile,
            debug_port=debug_port,
        )
        wait_for_manual_login(
            debug_port,
            timeout=args.timeout,
            browser_process=browser_process,
        )
        # WebDriver yalnız elle giriş bittikten sonra cookie okumak için bağlanır.
        driver = attach_after_login(debug_port)
        cookies = wait_for_required_cookies(driver)
        save_cookies(cookies, args.output)
        print(f"Giriş algılandı. {len(cookies)} cookie kaydedildi: {args.output}")
        if args.import_docker:
            import_via_docker(args.output)
            print("Cookie'ler collector state store'a şifreli olarak aktarıldı.")
        elif args.import_local:
            import_via_local_package(args.output)
        else:
            print(
                "Collector'a aktarmak için:\n"
                f"  python {Path(__file__).name} --import-docker\n"
                "veya\n"
                f"  timeline-cti-cli import-cookies {args.output}"
            )
        return 0
    except KeyboardInterrupt:
        print("\nİptal edildi.", file=sys.stderr)
        return 130
    except (TimeoutError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1
    finally:
        if driver is not None:
            driver.quit()
        if browser_process is not None and browser_process.poll() is None:
            browser_process.terminate()
            try:
                browser_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                browser_process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
