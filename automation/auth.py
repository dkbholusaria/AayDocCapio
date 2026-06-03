import re
import asyncio
from playwright.async_api import Page, BrowserContext
from automation.downloader import update_browser_status


async def _dump_inputs(page: Page, log):
    """Log every visible input/button on page for post-failure diagnosis."""
    try:
        info = await page.evaluate("""() => {
            const out = [];
            for (const el of document.querySelectorAll('input, button, a, [role="button"]')) {
                const r = el.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) continue;
                out.push({
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || '',
                    id: el.id || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    text: (el.innerText || el.value || '').trim().replace(/\\s+/g,' ').slice(0,60),
                });
            }
            return { url: location.href, controls: out };
        }""")
        log("[Auth] --- Page diagnostics ---")
        log(f"[Auth] URL: {info['url']}")
        for c in info.get("controls", []):
            log(f"[Auth]   {c}")
        log("[Auth] --- End diagnostics ---")
    except Exception as e:
        log(f"[Auth] dumpInputs failed: {e}")


async def _click_btn(page: Page, log, timeout=5000) -> bool:
    """Click the first enabled Continue / Submit button. Returns True if clicked."""
    for sel in (
        "button:has-text('Continue')",
        "button[type='submit']",
    ):
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=timeout):
                log(f"[Auth]   clicking: {sel}")
                await btn.click(timeout=timeout)
                return True
        except Exception:
            pass
    return False


# ── Main login function ───────────────────────────────────────────────────────

async def login_itd(user_id: str, password: str, log_callback, context: BrowserContext) -> Page:
    uid_masked = (user_id[:3] + "XXXXXXX") if user_id and len(user_id) >= 3 else "UNKNOWN"

    log_callback("[Auth] Opening new page for ITD login...")
    page = await context.new_page()
    await update_browser_status(page, "Auth: Connecting to ITD Portal...")
    page.on("dialog", lambda d: asyncio.create_task(d.dismiss()))

    log_callback("[Auth] Loading ITD Portal...")
    await page.goto(
        "https://eportal.incometax.gov.in/iec/foservices/#/login",
        wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_load_state("networkidle", timeout=30000)
    await asyncio.sleep(2)

    # ── Step 1: Fill PAN ─────────────────────────────────────────────────────
    log_callback(f"[Auth] Entering User ID: {uid_masked}")
    await update_browser_status(page, f"Auth: Entering User ID ({uid_masked})...")

    await page.fill("id=panAdhaarUserId", user_id)
    await asyncio.sleep(0.5)

    # ── Step 2: Click Continue after PAN ─────────────────────────────────────
    log_callback("[Auth] Clicking Continue after PAN...")
    await _click_btn(page, log_callback, timeout=10000)

    # ── Step 3: Wait for SAM checkbox, tick it, click Continue ───────────────
    log_callback("[Auth] Waiting for SAM page (Step 2)...")
    await update_browser_status(page, "Auth: Waiting for Step 2...")

    sam_found = False
    for _ in range(100):    # 100 × 300ms = 30s
        await asyncio.sleep(0.3)
        try:
            sam_found = await page.locator("id=passwordCheckBox-input").first.is_visible()
        except Exception:
            sam_found = False
        if sam_found:
            break

    if not sam_found:
        await _dump_inputs(page, log_callback)
        raise RuntimeError("SAM page (Step 2) did not appear after PAN entry.")

    log_callback("[Auth] SAM page ready — ticking checkbox...")
    try:
        await page.check("id=passwordCheckBox-input", force=True)
    except Exception:
        await page.evaluate("""() => {
            const cb = document.getElementById('passwordCheckBox-input');
            if (cb && !cb.checked) cb.click();
        }""")

    # ── Step 4: Select Password login method ─────────────────────────────────
    log_callback("[Auth] Clicking Continue on SAM page...")
    await _click_btn(page, log_callback, timeout=5000)

    # The portal shows radio buttons: Password / OTP — select Password
    log_callback("[Auth] Selecting Password login method...")
    try:
        pwd_radio = page.locator("xpath=//label[normalize-space(text())='Password']").first
        if await pwd_radio.is_visible(timeout=3000):
            await pwd_radio.click()
            log_callback("[Auth] Password radio selected.")
    except Exception as e:
        log_callback(f"[Auth] Password radio not found (may already be selected): {e}")

    # ── Step 5: Wait for password field, fill it ──────────────────────────────
    log_callback("[Auth] Waiting for password field...")
    await update_browser_status(page, "Auth: Entering password...")

    try:
        await page.wait_for_selector("id=loginPasswordField", state="visible", timeout=5000)
    except Exception:
        await _dump_inputs(page, log_callback)
        raise RuntimeError("Password field did not appear after selecting login method.")

    log_callback("[Auth] Entering password...")
    await page.fill("id=loginPasswordField", password)

    # ── Step 6: Submit with up to 4 attempts ─────────────────────────────────
    log_callback("[Auth] Submitting credentials...")
    await update_browser_status(page, "Auth: Submitting credentials...")

    async def _submit_once(attempt: int) -> bool:
        if attempt > 1:
            log_callback(f"[Auth] Submit attempt {attempt}/4...")
            await asyncio.sleep(3)

        clicked = await _click_btn(page, log_callback, timeout=10000)
        if not clicked:
            log_callback("[Auth] Continue not found — pressing Enter")
            try:
                await page.locator("id=loginPasswordField").first.press("Enter")
            except Exception:
                pass

        # Wait up to 7.5s for URL change or known error
        for _ in range(15):
            await asyncio.sleep(0.5)

            if "dashboard" in page.url.lower():
                return True

            # loginMaxAttemptsPopup — too many attempts; click "Login Here"
            try:
                if await page.locator("id=loginMaxAttemptsPopup").first.is_visible(timeout=300):
                    log_callback("[Auth] Max-attempts popup — clicking Login Here...")
                    try:
                        await page.locator("button:has-text('Login Here')").first.click(timeout=3000)
                    except Exception:
                        pass
                    try:
                        await page.wait_for_url(
                            lambda u: "dashboard" in u.lower(), timeout=10000)
                        return True
                    except Exception:
                        return False
            except Exception:
                pass

            # Inline error — wrong password
            try:
                err = page.locator(
                    "mat-error, .mat-error1, .mat-mdc-form-field-error, "
                    ".error-msg, div[role='alert']").first
                if await err.is_visible(timeout=300):
                    err_text = (await err.inner_text()).lower()
                    if "invalid password" in err_text:
                        raise RuntimeError("AUTHENTICATION FAILED: Incorrect Password.")
                    return False   # other error — retry
            except RuntimeError:
                raise
            except Exception:
                pass

        return False

    login_success = False
    for attempt in range(1, 5):
        try:
            login_success = await _submit_once(attempt)
        except RuntimeError:
            raise
        if login_success:
            break

    if not login_success:
        await _dump_inputs(page, log_callback)
        raise RuntimeError("Could not reach dashboard after 4 submit attempts.")

    log_callback("[Auth] Login successful.")
    await update_browser_status(page, "Auth: Login Successful!")

    # ── Step 7: Dashboard settling ────────────────────────────────────────────
    log_callback("[Auth] Dashboard settling...")
    await update_browser_status(page, "Auth: Dashboard settling...")
    try:
        await page.wait_for_selector(
            "//div[contains(text(), 'Welcome Back')] | //a[normalize-space(.)='AIS']",
            state="visible", timeout=20000)
        await asyncio.sleep(4)
    except Exception:
        log_callback("[Warning] Dashboard sentinel timed out. Proceeding cautiously.")

    log_callback(f"[Auth] Dashboard ready: {page.url}")
    return page


# ── Logout ────────────────────────────────────────────────────────────────────

async def logout_itd(page: Page, log_callback):
    try:
        log_callback("[Auth] Initiating logout...")
        await update_browser_status(page, "Auth: Logging out...")

        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(1)
        except Exception:
            pass

        # Strategy 1: direct logout link / button
        try:
            btn = page.locator(
                "//a[normalize-space(text())='Log Out' or normalize-space(text())='Logout'] | "
                "//button[normalize-space(text())='Log Out' or normalize-space(text())='Logout']"
            ).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                log_callback("[Auth] Logout button clicked.")
                await asyncio.sleep(2)
        except Exception:
            pass

        # Strategy 2: profile menu → logout item
        if "login" not in page.url.lower():
            try:
                profile = page.locator(
                    "//a[contains(@class,'profile') or contains(@class,'user') or "
                    "contains(@id,'profile')] | "
                    "//span[contains(@class,'user-name') or contains(@class,'user-profile')] | "
                    "//div[contains(@class,'profile-icon')]"
                ).first
                if await profile.is_visible(timeout=4000):
                    await profile.click()
                    await asyncio.sleep(1.5)
                    item = page.locator(
                        "//a[normalize-space(text())='Log Out' or normalize-space(text())='Logout'] | "
                        "//span[normalize-space(text())='Log Out' or normalize-space(text())='Logout'] | "
                        "//button[normalize-space(text())='Log Out' or normalize-space(text())='Logout']"
                    ).first
                    await item.click()
                    log_callback("[Auth] Logout via profile menu.")
                    await asyncio.sleep(2)
            except Exception:
                pass

        # Strategy 3: force-navigate to login page
        if "login" not in page.url.lower():
            try:
                await page.goto(
                    "https://eportal.incometax.gov.in/iec/foservices/#/login",
                    wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(1.5)
                log_callback("[Auth] Session cleared via login page navigation.")
            except Exception as e:
                log_callback(f"[Auth] Logout strategy 3 failed: {e}")

        for _ in range(10):
            await asyncio.sleep(0.5)
            if "login" in page.url.lower():
                log_callback("[Auth] Successfully logged out.")
                break

    except Exception as e:
        log_callback(f"[Auth] Logout warning: {e}")
    finally:
        try:
            await page.close()
        except Exception:
            pass
