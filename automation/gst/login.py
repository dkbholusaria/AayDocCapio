"""Log in to the GST portal (services.gst.gov.in).

Flow, verified against the live portal while the feature was built:

1. open the login page and submit the credentials form once (the captcha image
   only appears after that);
2. read ``#imgCaptcha`` with :mod:`automation.gst.captcha`;
3. if the read is not confident, point the image at a fresh
   ``/services/captcha?rnd=...`` and read again (up to ``max_refresh``);
4. submit; the portal reports failures in ``.err`` elements:

   * ``Enter valid Letters shown`` -> the captcha was wrong;
   * ``Invalid Username or Password`` -> the captcha was accepted, credentials
     were not (useful as a safe oracle while testing).

5. after a rejected captcha the portal clears the username/password inputs, so
   they are refilled before the next attempt;
6. success is detected by leaving the login route (``/services/auth/...``).

Nothing here logs a password, and the captcha answer is only kept in the
returned dict.
"""
from __future__ import annotations

import asyncio

from playwright.async_api import Page, TimeoutError as PWTimeout

from automation.gst import captcha as _captcha

LOGIN_URL = "https://services.gst.gov.in/services/login"

_REFRESH_JS = """() => {
    const img = document.getElementById('imgCaptcha');
    img.src = '/services/captcha?rnd=' + Date.now();
    return img.src;
}"""

_ERR_JS = """() => Array.from(
        document.querySelectorAll('.err,[class*=err],[class*=alert]'))
    .filter(e => e.offsetParent !== null)
    .map(e => e.innerText.trim()).filter(t => t.length > 0).join(' | ')"""

_ACCOUNT_JS = """() => {
    const body = document.body ? document.body.innerText : '';
    const m = body.match(
        /([A-Z0-9][A-Z0-9 &.,()\\-]{2,80}(?:PRIVATE LIMITED|LIMITED|LLP|PVT\\.? LTD|PROPRIETOR|ENTERPRISES|AND SONS))\\s*to GST Common Portal/i);
    if (m) return m[1].trim();
    const m2 = body.match(/\\bWelcome\\s+([A-Z0-9][A-Z0-9 &.,()\\-]{2,80})/);
    return m2 ? m2[1].trim() : '';
}"""


def mask(username: str) -> str:
    """``GSTLOGIN01`` -> ``GST***``: safe for logs."""
    u = (username or "").strip()
    return (u[:3] + "***") if len(u) >= 3 else "***"


def classify_error(text: str) -> str:
    """Map the portal's error text to one of: wrong, credentials, otp, unknown."""
    t = (text or "").lower()
    if "valid letters" in t:
        return "wrong"
    if "invalid username" in t or "invalid user" in t or "does not exist" in t:
        return "credentials"
    if "otp" in t or "one time password" in t:
        return "otp"
    return "unknown"


async def _captcha_visible(page: Page) -> bool:
    el = await page.query_selector("#imgCaptcha")
    try:
        return bool(el) and await el.is_visible()
    except Exception:
        return False


async def _fill_credentials(page: Page, username: str, password: str):
    await page.fill("#username", username)
    await page.fill("#user_pass", password)


async def _open_captcha(page: Page, username: str, password: str, timeout_ms: int):
    """Load the login page and submit once so the captcha form is rendered."""
    await page.goto(LOGIN_URL, wait_until="networkidle", timeout=timeout_ms)
    await _fill_credentials(page, username, password)
    await page.click("button:has-text('LOGIN')")
    await page.wait_for_selector("#imgCaptcha", state="visible", timeout=timeout_ms)
    await page.wait_for_timeout(1200)


async def login_gst(page: Page, username: str, password: str, log_callback,
                    max_refresh: int = 6, max_wrong: int = 3,
                    pace_ms: int = 1200, timeout_ms: int = 60000) -> dict:
    """Log in and return a result dict.

    Keys: ``ok`` (credentials accepted), ``reason`` (accepted/credentials/otp/
    too-many-wrong/exhausted/error), ``account_name`` (when known), ``url``,
    ``captcha_reads``, ``attempts``, ``error_text``.
    """
    masked = mask(username)
    log = log_callback or (lambda msg: None)
    wrong_run = 0
    attempts = 0
    reads = 0
    error_text = ""

    try:
        log(f"[GST] Opening GST portal for {masked}...")
        await _open_captcha(page, username, password, timeout_ms)

        while attempts < max_wrong + 2:
            attempts += 1
            chosen = None
            refreshes = 0
            for _ in range(max_refresh + 1):
                el = await page.query_selector("#imgCaptcha")
                shot = await el.screenshot()
                reads += 1
                result = await asyncio.to_thread(_captcha.solve, shot)
                log(f"[GST]   captcha read {refreshes}: {result['code'] or '(unsure)'}"
                    f" {result['confidence']} ({result['reason']})")
                if _captcha.should_submit(result):
                    chosen = result
                    break
                refreshes += 1
                if refreshes > max_refresh:
                    break
                await page.evaluate(_REFRESH_JS)
                await page.wait_for_timeout(pace_ms)

            if chosen is None:
                log(f"[GST] captcha unreadable after {refreshes} refreshes")
                if attempts >= 2:
                    return _result(False, "exhausted", page, attempts, reads, error_text)
                await _open_captcha(page, username, password, timeout_ms)
                continue

            src0 = await page.get_attribute("#imgCaptcha", "src")
            await page.wait_for_timeout(pace_ms)
            await page.fill("#captcha", chosen["code"])
            await page.click("button:has-text('LOGIN')")
            try:
                await page.wait_for_function(
                    "s => { const i = document.getElementById('imgCaptcha');"
                    " return !i || i.getAttribute('src') !== s; }",
                    arg=src0, timeout=10000)
            except PWTimeout:
                pass
            await page.wait_for_timeout(3000)

            error_text = await page.evaluate(_ERR_JS)
            if error_text:
                parts = []
                for part in error_text.split(" | "):
                    if part and part not in parts:
                        parts.append(part)
                error_text = " | ".join(parts)
            verdict = classify_error(error_text)
            log(f"[GST] submit {chosen['code']} -> {verdict}"
                f"{(' | ' + error_text[:120]) if error_text else ''}")

            if verdict == "wrong":
                wrong_run += 1
                if wrong_run >= max_wrong:
                    return _result(False, "too-many-wrong", page, attempts,
                                   reads, error_text)
                # The portal clears the credential inputs on a failed captcha.
                try:
                    await _fill_credentials(page, username, password)
                    await page.fill("#captcha", "")
                except Exception:
                    pass
                if await _captcha_visible(page):
                    await page.evaluate(_REFRESH_JS)
                    await page.wait_for_timeout(pace_ms)
                continue

            if verdict == "credentials":
                return _result(True, "credentials", page, attempts, reads, error_text)
            if verdict == "otp":
                return _result(True, "otp", page, attempts, reads, error_text)

            if not await _captcha_visible(page) or "services/login" not in page.url:
                account = ""
                try:
                    account = await page.evaluate(_ACCOUNT_JS)
                except Exception:
                    pass
                return _result(True, "accepted", page, attempts, reads, error_text,
                               account=account or None)
            await page.wait_for_timeout(2000)

        return _result(False, "too-many-wrong", page, attempts, reads, error_text)
    except Exception as exc:  # network / selector failures
        log(f"[GST] login error: {exc}")
        return _result(False, "error", page, attempts, reads, str(exc)[:200])


def _result(ok, reason, page, attempts, reads, error_text, account=None):
    return {
        "ok": bool(ok),
        "reason": reason,
        "account_name": account,
        "url": getattr(page, "url", ""),
        "attempts": attempts,
        "captcha_reads": reads,
        "error_text": (error_text or "")[:300],
    }
