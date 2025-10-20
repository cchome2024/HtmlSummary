import os
import asyncio
import json
from typing import Optional, Tuple
from urllib.parse import urlparse


MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.40(0x1800282e) NetType/WIFI Language/zh_CN"
)


class BrowserFetchError(RuntimeError):
    pass


def _storage_path_for(url: str) -> str:
    from pathlib import Path
    o = urlparse(url)
    domain = (o.hostname or "generic").replace(":", "_")
    base = Path(__file__).resolve().parent.parent / "storage"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / f"playwright-{domain}.json")


async def fetch_text_via_playwright(
    url: str,
    timeout_ms: int = 30000,
    headless: Optional[bool] = None,
    persist_session: bool = False,
) -> Tuple[str, str]:
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as e:
        raise BrowserFetchError(
            "Playwright not installed. Install with: pip install playwright && playwright install chromium"
        ) from e

    if headless is None:
        headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "1").strip()
        headless = headless_env not in ("0", "false", "False")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=headless)
        except Exception as e:
            raise BrowserFetchError(
                f"Failed to launch Chromium: {e}. Run: playwright install chromium"
            ) from e

        storage_state = None
        storage_path = _storage_path_for(url)
        if persist_session and os.path.exists(storage_path):
            storage_state = storage_path

        context = await browser.new_context(
            user_agent=MOBILE_UA,
            viewport={"width": 390, "height": 844},
            extra_http_headers={
                "Referer": "https://mp.weixin.qq.com/",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            storage_state=storage_state,
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)

            # Scroll to trigger lazy load
            for _ in range(10):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(200)

            selector = "#js_content, .rich_media_content"
            try:
                await page.wait_for_selector(selector, timeout=8000)
            except Exception:
                # continue; we'll still try to extract body text
                pass

            # Detect common verification/abnormal environment banners
            try:
                abnormal = await page.evaluate(
                    """
                    () => {
                      const txt = document.body ? document.body.innerText : '';
                      return /去验证|当前.*环境异常|验证后继续/.test(txt);
                    }
                    """
                )
            except Exception:
                abnormal = False
            if abnormal and headless:
                raise BrowserFetchError(
                    "Target requires verification. Switch to headful mode to complete verification: set PLAYWRIGHT_HEADLESS=0 or enable headful in UI."
                )

            title = await page.evaluate(
                """
                () => {
                  const t = document.querySelector('#activity-name, h1.rich_media_title');
                  return (t && t.innerText) || document.title || '';
                }
                """
            )
            text = await page.evaluate(
                """
                () => {
                  // Prefer article content; remove common footer/toolbars to avoid noise like “赞/在看”
                  const root = document.querySelector('#js_content, .rich_media_content');
                  const pick = root ? root.cloneNode(true) : document.body.cloneNode(true);
                  const removeSel = [
                    '.rich_media_tool', '#js_toobar3', '.weui-dialog', '.weui-mask', '#js_cmt_area',
                    '.profile_container', '.related_article', '.footer', '.meta_primary', '.qr_code_pc'
                  ];
                  removeSel.forEach(s => pick.querySelectorAll(s).forEach(el => el.remove()));
                  return pick ? pick.innerText : (document.body ? document.body.innerText : '');
                }
                """
            )
            if persist_session:
                try:
                    await context.storage_state(path=storage_path)
                except Exception:
                    pass
            return (str(title or "").strip(), str(text or "").strip())
        finally:
            await context.close()
            await browser.close()
