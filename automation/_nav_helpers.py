import asyncio

from playwright.async_api import Page

from automation.diagnostics import capture_failure


async def open_hamburger(page: Page, log_callback, prefix: str = "NAV") -> None:
    """
    Open the collapsed nav (☰ = #hamburgerOpen) so e-File becomes clickable.
    a#e-File exists in the DOM but only works once the panel is open, so click
    the hamburger first whenever the button is present. Scroll to top first
    in case the page is scrolled down and the nav bar is out of view.
    """
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)
    except Exception:
        pass

    for sel in ("#hamburgerOpen", "button[aria-label*='menu' i]", ".hamburger"):
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=500):
                log_callback(f"[{prefix}] Opening hamburger menu: {sel}")
                try:
                    await btn.click(timeout=3000)
                except Exception:
                    await btn.click(force=True, timeout=3000)
                await asyncio.sleep(1)
                return
        except Exception:
            continue


async def hover_to_income_tax_returns(page: Page, log_callback, prefix: str = "NAV") -> None:
    """
    Open e-File then hover Income Tax Returns on the ITD dashboard nav,
    leaving the submenu open so the caller can click its own form-specific
    menu item next (e.g. "View Form 26AS", "View Form 168", "View Filed
    Returns").

    The e-File trigger (`<a id="e-File" class="mat-mdc-menu-trigger">`) is a
    stock Angular Material MatMenuTrigger, whose built-in mechanism opens on
    CLICK. A live diagnostics capture (automation/diagnostics.py) confirmed
    that when this ran as the second e-File-based handler in a batch,
    `.hover()` moved the mouse and "succeeded" per Playwright but the menu
    panel stayed empty (`<mat-menu><!----></mat-menu>`) — the portal's hover
    behaviour appears to depend on custom glue script that isn't reliably
    active a second time in the same tab session. Click is the native,
    always-on open mechanism and doesn't depend on that glue, so it's used
    here instead. The nested "Income Tax Returns" submenu below is native
    Angular Material CDK hover-to-reveal behaviour once the parent menu is
    genuinely open, and stays hover-based.
    """
    log_callback(f"[{prefix}] Opening e-File menu...")
    # Retry the full wait+click cycle — dashboard Angular nav may take time to
    # mount even after the overlay clears. Each attempt waits up to 30s for the
    # element to appear, then tries to click it.
    for _attempt in range(4):
        try:
            efile = page.locator("//*[normalize-space(.)='e-File']").first
            await efile.wait_for(state="visible", timeout=30000)
            await efile.click(timeout=10000)
            break
        except Exception:
            if _attempt == 3:
                await capture_failure(page, log_callback, f"{prefix}_efile_hover_failed")
                raise
            log_callback(f"[{prefix}] e-File menu not ready (attempt {_attempt + 1}/4) — waiting...")
            # Nudge the page to help Angular finish rendering the nav
            try:
                await page.keyboard.press("Escape")
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            await asyncio.sleep(5)
    await asyncio.sleep(1.0)
    log_callback(f"[{prefix}] Hovering over Income Tax Returns...")
    returns = page.locator("//*[text()='Income Tax Returns']").first
    try:
        await returns.wait_for(state="visible", timeout=30000)
    except Exception:
        await capture_failure(page, log_callback, f"{prefix}_income_tax_returns_hover_failed")
        raise
    await returns.hover()
    await asyncio.sleep(1.0)
