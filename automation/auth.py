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

async def login_itd(user_id: str, password: str, log_callback, context: BrowserContext,
                    is_running=None) -> Page:
    uid_masked = (user_id[:3] + "XXXXXXX") if user_id and len(user_id) >= 3 else "UNKNOWN"

    log_callback("[Auth] Opening new page for ITD login...")
    page = await context.new_page()
    await update_browser_status(page, "Auth: Connecting to ITD Portal...")
    page.on("dialog", lambda d: asyncio.create_task(d.dismiss()))

    try:
        return await _do_login(page, user_id, uid_masked, password, log_callback, is_running)
    except Exception:
        # Close the orphaned login page so failed clients don't leak tabs.
        try:
            await page.close()
        except Exception:
            pass
        raise


async def _do_login(page, user_id, uid_masked, password, log_callback, is_running=None):

    _ITD_LOGIN = "https://eportal.incometax.gov.in/iec/foservices/#/login"
    for _nav_attempt in range(1, 4):
        try:
            log_callback(f"[Auth] Loading ITD Portal{f' (retry {_nav_attempt})' if _nav_attempt > 1 else ''}...")
            await page.goto(_ITD_LOGIN, wait_until="domcontentloaded", timeout=90000)
            break
        except Exception as _nav_err:
            err_str = str(_nav_err)
            # Transient network errors — retry with a short backoff
            if any(k in err_str for k in ("ERR_EMPTY_RESPONSE", "ERR_CONNECTION_RESET",
                                           "ERR_CONNECTION_REFUSED", "ERR_NAME_NOT_RESOLVED",
                                           "ERR_TIMED_OUT", "net::")):
                if _nav_attempt < 3:
                    log_callback(f"[Auth] Portal unreachable ({err_str.split(chr(10))[0].strip()}) — retrying in 5 s…")
                    await asyncio.sleep(5)
                    continue
            raise  # non-network error or final attempt — propagate

    # Real Chrome keeps background connections alive so networkidle never fires.
    # domcontentloaded is sufficient; wait for the Angular app to mount the login form.
    await asyncio.sleep(3)

    # ── Maintenance check ────────────────────────────────────────────────────
    # The portal serves a plain HTML maintenance page instead of the Angular
    # app during downtime. Detect it early so we show a clear status.
    try:
        body_text = (await page.inner_text("body")).lower()
        if "maintenance" in body_text or "website will be down" in body_text or "maintance" in body_text:
            import re as _re
            # Try to extract the window from the page text
            raw = await page.inner_text("body")
            m = _re.search(r"([\d]{1,2}\s+\w+\s+\d{4}[^.]*?to[^.]*?IST)", raw, _re.IGNORECASE)
            window = f" ({m.group(1).strip()})" if m else ""
            raise RuntimeError(
                f"ITD portal is under scheduled maintenance{window}. "
                f"Try again after the maintenance window."
            )
    except RuntimeError:
        raise
    except Exception:
        pass  # page.inner_text failed (e.g. blank page) — proceed normally

    # ── Step 1: Fill PAN ─────────────────────────────────────────────────────
    log_callback(f"[Auth] Entering User ID: {uid_masked}")
    await update_browser_status(page, f"Auth: Entering User ID ({uid_masked})...")

    await page.fill("id=panAdhaarUserId", user_id)
    await asyncio.sleep(0.5)

    # ── Step 2: Click Continue after PAN ─────────────────────────────────────
    log_callback("[Auth] Clicking Continue after PAN...")
    await _click_btn(page, log_callback, timeout=20000)

    # Check for errors shown inline on the PAN screen after Continue
    await asyncio.sleep(1)
    try:
        page_text = (await page.inner_text("body")).lower()
        if "account has been locked" in page_text or "e-filing account" in page_text and "locked" in page_text:
            raise RuntimeError(
                "ACCOUNT LOCKED: This e-filing account has been locked due to security reasons. "
                "The client must unlock their account at the ITD portal before it can be automated.")
        if "pan does not exist" in page_text or "pan is not registered" in page_text:
            raise RuntimeError(
                "AUTHENTICATION FAILED: PAN does not exist on the ITD portal. "
                "Please verify the PAN is correct and registered at eportal.incometax.gov.in.")
    except RuntimeError:
        raise
    except Exception:
        pass

    # ── Step 3: Wait for SAM checkbox, tick it, click Continue ───────────────
    log_callback("[Auth] Waiting for SAM page (Step 2)...")
    await update_browser_status(page, "Auth: Waiting for Step 2...")

    sam_found = False
    for _ in range(200):    # 200 × 300ms = 60s
        await asyncio.sleep(0.3)
        try:
            sam_found = await page.locator("id=passwordCheckBox-input").first.is_visible()
        except Exception:
            sam_found = False
        if sam_found:
            break

        # Fast-fail if locked account or invalid PAN error appears during the wait
        try:
            page_text = (await page.inner_text("body")).lower()
            if "account has been locked" in page_text or ("e-filing account" in page_text and "locked" in page_text):
                raise RuntimeError(
                    "ACCOUNT LOCKED: This e-filing account has been locked due to security reasons. "
                    "The client must unlock their account at the ITD portal before it can be automated.")
            if "pan does not exist" in page_text or "pan is not registered" in page_text:
                raise RuntimeError(
                    "AUTHENTICATION FAILED: PAN does not exist on the ITD portal. "
                    "Please verify the PAN is correct and registered at eportal.incometax.gov.in.")
        except RuntimeError:
            raise
        except Exception:
            pass

        # B-04: portal may show an "active session" / "already logged in" dialog.
        # Detect any Continue/Proceed/Yes button inside a modal and click it.
        try:
            active_session = await page.evaluate("""() => {
                const keywords = ['already logged', 'active session', 'session exists',
                                  'do you wish to continue', 'existing session'];
                const body = document.body.innerText.toLowerCase();
                return keywords.some(k => body.includes(k));
            }""")
            if active_session:
                for dismiss_sel in (
                    "button:has-text('Continue')",
                    "button:has-text('Proceed')",
                    "button:has-text('Yes')",
                    "button:has-text('OK')",
                ):
                    try:
                        btn = page.locator(dismiss_sel).first
                        if await btn.is_visible(timeout=500):
                            log_callback("[Auth] Active session dialog detected — dismissing...")
                            await btn.click()
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        pass
        except Exception:
            pass

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
    await _click_btn(page, log_callback, timeout=15000)

    # After SAM Continue the portal may show a method-selection page
    # (#/login/otpOptions) with Password and OTP radios, OR may skip straight
    # to the password field. Wait briefly to see which page we land on.
    log_callback("[Auth] Waiting for method selection or password field...")
    await update_browser_status(page, "Auth: Selecting login method...")

    _method_selected = False
    for _sel in (
        # Angular Material radio label — portal renders "Password" as label text
        "xpath=//label[contains(normalize-space(.), 'Password') and not(contains(normalize-space(.), 'OTP'))]",
        # Fallback: first mat-radio input (Password is always radio 0)
        "input[type='radio']#mat-radio-0-input",
        "input[type='radio']:first-of-type",
    ):
        try:
            await page.wait_for_selector(_sel, state="visible", timeout=4000)
            await page.locator(_sel).first.click(force=True)
            log_callback(f"[Auth] Password method selected via: {_sel}")
            _method_selected = True
            break
        except Exception:
            pass

    if _method_selected:
        # Method selection page needs its own Continue click
        log_callback("[Auth] Clicking Continue after selecting Password method...")
        await _click_btn(page, log_callback, timeout=10000)
    else:
        log_callback("[Auth] Method selection page not seen — assuming password field follows directly.")

    # ── Step 5: Wait for password field, fill it ──────────────────────────────
    log_callback("[Auth] Waiting for password field...")
    await update_browser_status(page, "Auth: Entering password...")

    try:
        await page.wait_for_selector("id=loginPasswordField", state="visible", timeout=15000)
    except Exception:
        await _dump_inputs(page, log_callback)
        raise RuntimeError("Password field did not appear after selecting login method.")

    log_callback("[Auth] Entering password...")
    await page.fill("id=loginPasswordField", password)

    # Guard: if portal already navigated to OTP page before password submit
    if "otpOptions" in page.url or "otpoptions" in page.url.lower():
        raise RuntimeError(
            "AUTHENTICATION FAILED: This account has 2FA (OTP) enabled on the ITD portal. "
            "Automated login is not possible. The client must disable 2FA or log in manually.")

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

            # 2FA OTP page — portal is requiring OTP after password (2FA enabled on account)
            if "otpOptions" in page.url or "otpoptions" in page.url.lower():
                raise RuntimeError(
                    "AUTHENTICATION FAILED: This account has 2FA (OTP) enabled on the ITD portal. "
                    "Automated login is not possible. The client must disable 2FA or log in manually.")

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
                        # ITD throttles the session after a max-attempts popup — the 
                        # Angular router may silently drop navigation events for a few
                        # seconds. Wait for the portal to fully recover before returning.
                        log_callback("[Auth] Rate-limit recovered — waiting for session to stabilise...")
                        await asyncio.sleep(6)
                        return True
                    except Exception:
                        return False
            except Exception:
                pass

            # Inline error — wrong password / other auth failures
            try:
                err = page.locator(
                    "mat-error, .mat-error1, .mat-mdc-form-field-error, "
                    ".error-msg, .errorMessage, div[role='alert'], "
                    "span.error, .invalid-feedback").first
                if await err.is_visible(timeout=300):
                    err_text = (await err.inner_text()).strip()
                    err_low = err_text.lower()
                    log_callback(f"[Auth] Portal error: {err_text}")
                    # Any password/credential error → fail fast, don't retry
                    if any(k in err_low for k in (
                        "invalid password", "incorrect password", "wrong password",
                        "valid password", "password is incorrect",
                        "user id or password", "credentials")):
                        raise RuntimeError(
                            f"AUTHENTICATION FAILED: {err_text or 'Incorrect Password'}")
                    return False   # other transient error — retry
            except RuntimeError:
                raise
            except Exception:
                pass

        return False

    login_success = False
    for attempt in range(1, 5):
        if is_running is not None and not is_running():
            raise RuntimeError("Aborted by user.")
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
    sentinel_ok = False
    try:
        await page.wait_for_selector(
            "//div[contains(text(), 'Welcome Back')] | //a[normalize-space(.)='AIS']",
            state="visible", timeout=40000)
        sentinel_ok = True
        await asyncio.sleep(4)
    except Exception:
        log_callback("[Warning] Dashboard sentinel timed out. Proceeding cautiously.")

    # Ensure any loading overlay is gone before handing back the page.
    try:
        await page.locator(".customLoaderBackdrop").wait_for(state="hidden", timeout=30000)
        log_callback("[Auth] Loader overlay cleared.")
    except Exception:
        log_callback("[Auth] Loader overlay already gone or not present.")

    # If the sentinel never fired, give the Angular nav menu extra time to render
    # before handing back the page — without this the e-File hover times out.
    if not sentinel_ok:
        log_callback("[Auth] Waiting extra time for nav menu to render...")
        await asyncio.sleep(8)

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
