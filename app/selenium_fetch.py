import os
import time
import json
from typing import Tuple
from urllib.parse import urlparse

from .browser_fetch import BrowserFetchError, MOBILE_UA


def _find_chrome_path() -> str:
    # Prefer explicit env var
    p = os.getenv("CHROME_PATH") or os.getenv("GOOGLE_CHROME_BIN")
    if p and os.path.exists(p):
        return p
    # Common Windows paths
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Users\%USERNAME%\AppData\Local\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        path = os.path.expandvars(c)
        if os.path.exists(path):
            return path
    return ""


def _cookie_path_for(url: str) -> str:
    from pathlib import Path
    o = urlparse(url)
    domain = (o.hostname or "generic").replace(":", "_")
    base = Path(__file__).resolve().parent.parent / "storage"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / f"selenium-{domain}-cookies.json")


def fetch_text_via_selenium(url: str, headless: bool = True, persist_session: bool = False) -> Tuple[str, str]:
    try:
        from selenium import webdriver  # type: ignore
        from selenium.webdriver.chrome.options import Options  # type: ignore
        from selenium.webdriver.common.by import By  # type: ignore
    except Exception as e:
        raise BrowserFetchError(
            "Selenium not installed. Install with: pip install selenium undetected-chromedriver"
        ) from e

    chrome_path = _find_chrome_path()
    if not chrome_path:
        raise BrowserFetchError(
            "Chrome/Chromium not found. Set CHROME_PATH env or install Google Chrome."
        )

    options = Options()
    options.binary_location = chrome_path
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"--user-agent={MOBILE_UA}")
    options.add_argument("--window-size=390,844")

    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        raise BrowserFetchError(
            f"Failed to start Chrome via Selenium: {e}. You may need to allow Selenium Manager to download a driver, or install a matching chromedriver."
        ) from e

    try:
        # Set headers via CDP for subsequent requests
        try:
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd(
                "Network.setExtraHTTPHeaders",
                {
                    "headers": {
                        "Referer": "https://mp.weixin.qq.com/",
                        "Accept-Language": "zh-CN,zh;q=0.9",
                    }
                },
            )
        except Exception:
            pass

        # Load persisted cookies if any
        cookie_path = _cookie_path_for(url)
        try:
            if persist_session and os.path.exists(cookie_path):
                base_origin = f"{urlparse(url).scheme}://{urlparse(url).hostname}"
                driver.get(base_origin)
                with open(cookie_path, "r", encoding="utf-8") as fp:
                    cookies = json.load(fp)
                for c in cookies:
                    try:
                        # Selenium expects domain-less for current host in some versions
                        c2 = {k: v for k, v in c.items() if k != "domain"}
                        driver.add_cookie(c2)
                    except Exception:
                        pass
        except Exception:
            pass

        driver.get(url)

        # Simple scroll to trigger lazy-load
        for _ in range(12):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.25)

        title = driver.title or ""
        # Prefer WeChat selectors
        text = ""
        try:
            el = driver.find_element(By.CSS_SELECTOR, "#js_content, .rich_media_content")
            text = el.text
        except Exception:
            try:
                el = driver.find_element(By.TAG_NAME, "body")
                text = el.text
            except Exception:
                text = ""

        # Try more specific title
        try:
            t2 = driver.find_element(By.CSS_SELECTOR, "#activity-name, h1.rich_media_title").text
            if t2:
                title = t2
        except Exception:
            pass

        # Persist cookies
        try:
            if persist_session:
                cookies = driver.get_cookies()
                with open(cookie_path, "w", encoding="utf-8") as fp:
                    json.dump(cookies, fp, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return (title.strip(), text.strip())
    finally:
        try:
            driver.quit()
        except Exception:
            pass
