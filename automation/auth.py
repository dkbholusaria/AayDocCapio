import asyncio
import os
from playwright.async_api import Page, BrowserContext
from automation.downloader import update_browser_status

async def login_itd(user_id: str, password: str, log_callback, context: BrowserContext) -> Page:
    """
    Automates login into the Indian Income Tax Department (ITD) e-Filing portal.
    Returns the authenticated page instance.
    """
    log_callback("[Auth] Opening new page for ITD login...")
    page = await context.new_page()
    await update_browser_status(page, "Auth: Connecting to ITD Portal...")
    
    # Handle dialogs (like unexpected popups) by dismissing them
    page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))

    log_callback("[Auth] Loading ITD Portal (https://eportal.incometax.gov.in)...")
    await page.goto("https://eportal.incometax.gov.in/iec/foservices/#/login", wait_until="domcontentloaded", timeout=60000)
    
    log_callback(f"[Auth] Entering User ID: {user_id}")
    await update_browser_status(page, f"Auth: Entering User ID ({user_id})...")
    await page.fill("id=panAdhaarUserId", user_id)
    await asyncio.sleep(0.5)

    log_callback("[Auth] Portal verifying ID...")
    await update_browser_status(page, "Auth: Verifying User ID...")
    await asyncio.sleep(1) 
    
    continue_btn = page.locator("button:has-text('Continue')").first

    if not await continue_btn.is_enabled():
        error_msg = page.locator("xpath=//div[contains(@class, 'error') or contains(text(), 'Invalid')] | //div[contains(@aria-live, 'assertive')]").first
        try:
            if await error_msg.is_visible(timeout=1000):
                err_text = await error_msg.inner_text()
                raise RuntimeError(f"ID Rejected: {err_text.strip()}")
            else:
                raise RuntimeError("ID Rejected. Please verify credentials.")
        except Exception:
            raise RuntimeError("The portal blocked this User ID.")

    log_callback("[Auth] Clicking Continue...")
    await continue_btn.click()

    log_callback("[Auth] Waiting for Step 2 (Verification)...")
    try:
        success_selector = "id=passwordCheckBox-input"
        error_selector = "xpath=//mat-error[@role='alert'] | //*[contains(@class, 'mat-error1')] | //*[contains(@class, 'errorMessage')] | //*[contains(text(), 'Error')] | //*[contains(text(), 'does not exist')]"
        
        success = False
        rejection_msg = None
        for _ in range(30):
            if await page.is_visible(success_selector):
                success = True
                break
            if await page.is_visible(error_selector):
                rejection_msg = await page.inner_text(error_selector)
                break
            await asyncio.sleep(0.5)
            
        if rejection_msg: 
            raise RuntimeError(f"PORTAL REJECTION: {rejection_msg.strip()}")
        if not success: 
            raise RuntimeError("TRANSACTION FAILED: Portal did not transition to Step 2.")
            
    except Exception as e: 
        raise e
    
    log_callback("[Auth] Confirming Secure Access Message...")
    await page.check("id=passwordCheckBox-input", force=True)
    
    async def submit_with_retry(attempts=4):
        for i in range(attempts):
            if i > 0: await asyncio.sleep(3)
            log_callback(f"[Auth] Submitting (Attempt {i+1}/{attempts})...")
            await update_browser_status(page, f"Auth: Submitting Credentials (Attempt {i+1}/{attempts})...")
            try:
                btn = page.locator("button:has-text('Continue'), button[type='submit']").first
                await btn.click(timeout=10000)
            except Exception:
                continue
            
            for _ in range(15):
                await asyncio.sleep(0.5)
                if "dashboard" in page.url.lower(): 
                    return True
                if await page.is_visible("id=loginMaxAttemptsPopup"):
                    await page.click("button:has-text('Login Here')", timeout=5000)
                    try: 
                        await page.wait_for_url(lambda u: "dashboard" in u.lower(), timeout=10000)
                        return True
                    except Exception: 
                        break
                
                error_locator = page.locator("mat-error, .mat-error1, .mat-mdc-form-field-error, .error-msg, div[role='alert']").first
                if await error_locator.is_visible():
                    err_text = (await error_locator.inner_text()).lower()
                    if "invalid password" in err_text: 
                        raise RuntimeError("AUTHENTICATION FAILED: Incorrect Password.")
                    break
        return False

    # ---- LOGIN EXECUTION ----
    login_success = False
    try:
        if await page.is_visible("id=loginPasswordField", timeout=3000):
            await page.fill("id=loginPasswordField", password)
            login_success = await submit_with_retry()
        else:
            password_radio_label = page.locator("xpath=//label[normalize-space(text())='Password']").first
            if await password_radio_label.is_visible(timeout=3000):
                await password_radio_label.click()
                await asyncio.sleep(1) 
                await page.fill("id=loginPasswordField", password)
                login_success = await submit_with_retry()
        
        if not login_success:
            raise RuntimeError("Could not reach dashboard.")

        log_callback("[Auth] Login Successful.")
        await update_browser_status(page, "Auth: Login Successful!")

        log_callback("[Auth] Dashboard settling...")
        await update_browser_status(page, "Auth: Dashboard settling...")
        try:
            await page.wait_for_selector("//div[contains(text(), 'Welcome Back')] | //a[normalize-space(.)='AIS']", state="visible", timeout=20000)
            await asyncio.sleep(4.0) 
        except Exception:
            log_callback("[Warning] Dashboard sentinel timed out. Proceeding cautiously.")

        return page

    except Exception as e:
        raise e

async def logout_itd(page: Page, log_callback):
    """
    Automates logout from the ITD portal to clear the session for the next client.
    """
    try:
        log_callback("[Auth] Initiating ITD logout...")
        await update_browser_status(page, "Auth: Logging out...")
        
        # Close any open modal dialogs by pressing Escape to ensure the page structure is accessible
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(1.0)
        except Exception:
            pass

        # Try direct logout link first
        logout_btn = page.locator("//a[normalize-space(text())='Log Out' or normalize-space(text())='Logout'] | //button[normalize-space(text())='Log Out' or normalize-space(text())='Logout']").first
        if await logout_btn.is_visible(timeout=3000):
            await logout_btn.click()
            log_callback("[Auth] Logout button clicked.")
        else:
            # Click the user profile button on the top-right header to show dropdown menu
            profile_btn = page.locator("//a[contains(@class, 'profile') or contains(@class, 'user') or contains(@id, 'profile') or @aria-label='profile'] | //span[contains(@class, 'user-name') or contains(@class, 'user-profile')] | //div[contains(@class, 'profile-icon')]").first
            if await profile_btn.is_visible(timeout=4000):
                await profile_btn.click()
                await asyncio.sleep(1.5)
                
                logout_item = page.locator("//a[normalize-space(text())='Log Out' or normalize-space(text())='Logout'] | //span[normalize-space(text())='Log Out' or normalize-space(text())='Logout'] | //button[normalize-space(text())='Log Out' or normalize-space(text())='Logout']").first
                await logout_item.click()
                log_callback("[Auth] Logout dropdown item clicked.")
            else:
                # If we cannot find it, navigate to the portal login page to force end session/redirect
                log_callback("[Auth] Profile menu not found. Closing page.")
                
        # Wait to confirm logout redirect
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
