import os
import asyncio
from playwright.async_api import Page
from automation.downloader import update_browser_status

# ── Navigation ────────────────────────────────────────────────────────────────

async def _open_ais_portal(itd_page: Page, log) -> Page:
    """
    From the ITD dashboard, click the AIS nav link to open the Compliance Portal.
    Returns the compliance portal Page (may be a new tab or same tab).
    """
    log("[AIS] Opening Compliance Portal...")
    await update_browser_status(itd_page, "AIS: Opening Compliance Portal...")

    ais_link = itd_page.locator("a#AIS, a:has-text('AIS')").first
    try:
        await ais_link.wait_for(state="visible", timeout=15000)
    except Exception:
        raise Exception("AIS nav link not found on ITD dashboard.")

    try:
        async with itd_page.context.expect_page(timeout=15000) as new_page_info:
            await ais_link.click()
        portal = await new_page_info.value
        await portal.wait_for_load_state("domcontentloaded", timeout=30000)
        log(f"[AIS] Compliance Portal opened in new tab: {portal.url}")
    except Exception:
        portal = itd_page
        await portal.wait_for_load_state("domcontentloaded", timeout=30000)
        log(f"[AIS] Compliance Portal loaded in same tab: {portal.url}")

    # Wait for Angular SPA hydration
    await asyncio.sleep(3)
    await update_browser_status(portal, "AIS: Compliance Portal ready")
    return portal


async def _navigate_to_ais_tab(portal: Page, log):
    """
    Click the 'AIS' tab on the Compliance Portal to reveal the TIS/AIS tiles.
    Handles the Instructions page (first page on login).
    URL target: /complianceportal/ais/home
    """
    log("[AIS] Navigating to AIS tab...")

    # If on instructions page, click AIS tab
    ais_tab = portal.locator("a[role='tab']:has-text('AIS'), li:has-text('AIS') a, "
                             ".nav-link:has-text('AIS'), a.nav-item:has-text('AIS')").first
    try:
        await ais_tab.wait_for(state="visible", timeout=10000)
        await ais_tab.click()
        await asyncio.sleep(2)
        log(f"[AIS] AIS tab clicked. URL: {portal.url}")
    except Exception:
        log("[AIS] AIS tab not found — may already be on AIS page.")

    await update_browser_status(portal, "AIS: AIS tab active")


async def _select_fy(portal: Page, fiscal_year: str, log):
    """Select the given FY (e.g. '2024-25') from the FY dropdown."""
    log(f"[AIS] Selecting F.Y. {fiscal_year}...")
    try:
        toggle = portal.locator(
            "button.dropdown-toggle, [class*='dropdown'] button, button:has-text('F.Y.')"
        ).first
        await toggle.wait_for(state="visible", timeout=8000)
        await toggle.click()
        await asyncio.sleep(0.5)

        option = portal.locator(f".dropdown-item:has-text('{fiscal_year}')").first
        await option.wait_for(state="visible", timeout=5000)
        await option.click()
        log(f"[AIS] F.Y. {fiscal_year} selected.")
    except Exception:
        try:
            sel = portal.locator("select").first
            await sel.select_option(label=fiscal_year)
            log(f"[AIS] F.Y. {fiscal_year} selected via <select>.")
        except Exception as e:
            log(f"[Warning] Could not select F.Y. {fiscal_year}: {e}")
    await asyncio.sleep(1.5)


async def _open_tis_modal(portal: Page, log) -> bool:
    """
    Click the download icon on the TIS tile to open the TIS Download modal.
    Returns True if modal opened.
    """
    log("[TIS] Opening TIS download modal...")
    # TIS tile is the left tile — its download icon is the first ⬇ icon
    # The tile contains "Taxpayer Information Summary" text
    try:
        tis_tile = portal.locator(
            "div:has-text('Taxpayer Information Summary')"
        ).last
        dl_icon = tis_tile.locator("button, a, [role='button']").filter(
            has=portal.locator("[class*='download'], [title*='download' i], [aria-label*='download' i]")
        ).first
        # Fallback: just find the download icon buttons on page and take first (TIS is left tile)
        try:
            dl_icon_visible = await dl_icon.is_visible()
        except Exception:
            dl_icon_visible = False
        if not dl_icon_visible:
            dl_icon = portal.locator(
                "button[class*='download'], a[class*='download'], "
                "button[title*='Download' i], a[title*='Download' i]"
            ).first
        await dl_icon.wait_for(state="visible", timeout=10000)
        await dl_icon.click()
        await asyncio.sleep(1)
        log("[TIS] TIS modal opened.")
        return True
    except Exception as e:
        log(f"[TIS] Could not open TIS modal: {e}")
        return False


async def _open_ais_modal(portal: Page, log) -> bool:
    """
    Click the download icon on the AIS tile to open the AIS Download modal.
    Returns True if modal opened.
    """
    log("[AIS] Opening AIS download modal...")
    try:
        ais_tile = portal.locator(
            "div:has-text('Annual Information Statement')"
        ).last
        # AIS tile has two download icons — we click the first (PDF/JSON modal)
        dl_icons = ais_tile.locator(
            "button[class*='download'], a[class*='download'], "
            "button[title*='Download' i], a[title*='Download' i], "
            "button, a"
        ).filter(has=portal.locator("[class*='download'], mat-icon:has-text('download')"))
        count = await dl_icons.count()
        if count == 0:
            # Fallback: all download icons on page, AIS tile is right tile so take last
            dl_icons = portal.locator(
                "button[class*='download'], a[class*='download']"
            )
        # Click the first download icon inside AIS tile
        await dl_icons.first.wait_for(state="visible", timeout=10000)
        await dl_icons.first.click()
        await asyncio.sleep(1)
        log("[AIS] AIS modal opened.")
        return True
    except Exception as e:
        log(f"[AIS] Could not open AIS modal: {e}")
        return False


def _modal_locator(portal: Page):
    """Return a locator for the open Download modal."""
    return portal.locator(
        ".modal.show, .modal[style*='display: block'], "
        "[role='dialog'], .modal-dialog, mat-dialog-container"
    ).first


async def _close_modal(portal: Page, log):
    """Close the currently open modal via the × button."""
    try:
        modal = _modal_locator(portal)
        close_btn = modal.locator(
            "button[aria-label='Close'], button.close, "
            "button:has-text('×'), button:has-text('✕'), "
            "[aria-label='close' i]"
        ).first
        if await close_btn.is_visible(timeout=2000):
            await close_btn.click()
            await asyncio.sleep(0.5)
    except Exception:
        pass


# ── TIS Download ──────────────────────────────────────────────────────────────

async def download_tis(portal: Page, fiscal_year: str, download_dir: str,
                       log, pan: str = "") -> bool:
    """
    Download TIS PDF. Always instant — no generation step needed.
    Opens TIS tile modal → clicks Download → saves file.
    """
    os.makedirs(download_dir, exist_ok=True)
    fy_str = fiscal_year.replace("-", "_")
    prefix = f"{pan}-" if pan else ""

    opened = await _open_tis_modal(portal, log)
    if not opened:
        return False

    modal = _modal_locator(portal)
    try:
        await modal.wait_for(state="visible", timeout=5000)
    except Exception:
        log("[TIS] Modal did not appear.")
        return False

    # Modal has one row: "Taxpayer Information Summary (TIS) - PDF" + [Download]
    tis_file = os.path.join(download_dir, f"{prefix}TIS-{fy_str}.pdf")
    try:
        log("[TIS] Downloading TIS PDF...")
        await update_browser_status(portal, "AIS: Downloading TIS PDF...")
        dl_btn = modal.locator("button:has-text('Download')").first
        await dl_btn.wait_for(state="visible", timeout=8000)

        async with portal.context.expect_download(timeout=60000) as dl_info:
            await dl_btn.click()

        download = await dl_info.value
        await download.save_as(tis_file)
        log(f"[Victory] TIS PDF saved: {os.path.basename(tis_file)}")
        await _close_modal(portal, log)
        return True
    except Exception as e:
        log(f"[Warning] TIS download failed: {e}")
        await _close_modal(portal, log)
        return False


# ── AIS Request ───────────────────────────────────────────────────────────────

async def request_ais(portal: Page, fiscal_year: str, download_dir: str,
                      log, pan: str = "") -> dict:
    """
    Open AIS modal and click Download for AIS PDF.
    Three outcomes:
      - Instant: small file downloads immediately → saved to download_dir, returns {"status": "downloaded", "file": path}
      - Large:   success message with Reference ID → returns {"status": "requested", "ref_id": "..."}
      - Failed:  returns {"status": "failed"}

    NOTE: AIS JSON is skipped — it requires a CAPTCHA.
    """
    os.makedirs(download_dir, exist_ok=True)
    fy_str = fiscal_year.replace("-", "_")
    prefix = f"{pan}-" if pan else ""
    ais_file = os.path.join(download_dir, f"{prefix}AIS-{fy_str}.pdf")

    opened = await _open_ais_modal(portal, log)
    if not opened:
        return {"status": "failed"}

    modal = _modal_locator(portal)
    try:
        await modal.wait_for(state="visible", timeout=5000)
    except Exception:
        log("[AIS] Modal did not appear.")
        return {"status": "failed"}

    # Find the AIS PDF row — first row in modal
    # Row text: "Annual Information Statement (AIS) - PDF"
    try:
        ais_pdf_row = modal.locator(
            "tr:has-text('Annual Information Statement (AIS) - PDF'), "
            "div:has-text('Annual Information Statement (AIS) - PDF'), "
            "li:has-text('Annual Information Statement (AIS) - PDF')"
        ).first

        dl_btn = ais_pdf_row.locator("button:has-text('Download')").first
        if not await dl_btn.is_visible(timeout=5000):
            # Fallback: first Download button in modal
            dl_btn = modal.locator("button:has-text('Download')").first
            await dl_btn.wait_for(state="visible", timeout=5000)

        log("[AIS] Clicking Download for AIS PDF...")
        await update_browser_status(portal, "AIS: Requesting AIS PDF...")

        # Listen for instant download (small file) — 8s window
        try:
            async with portal.context.expect_download(timeout=8000) as dl_info:
                await dl_btn.click()
            download = await dl_info.value
            await download.save_as(ais_file)
            log(f"[Victory] AIS PDF downloaded instantly: {os.path.basename(ais_file)}")
            await _close_modal(portal, log)
            return {"status": "downloaded", "file": ais_file}
        except Exception:
            pass  # No instant download — check for success/request message

        # Check for "Success" / "Go To Activity History" message in modal
        await asyncio.sleep(1.5)
        try:
            success_text = await modal.inner_text()
        except Exception:
            success_text = ""

        # Look for Reference ID in the success message
        import re
        ref_match = re.search(r'Reference ID[:\s]*([A-Z0-9]+)', success_text, re.IGNORECASE)
        ref_id = ref_match.group(1) if ref_match else ""

        if ref_id or "activity history" in success_text.lower() or "submitted successfully" in success_text.lower():
            log(f"[AIS] AIS generation requested. Reference ID: {ref_id}")
            await _close_modal(portal, log)
            return {"status": "requested", "ref_id": ref_id, "fy": fiscal_year}

        # Button may have changed to "Go To Activity History"
        goto_btn = modal.locator("button:has-text('Go To Activity History')").first
        if await goto_btn.is_visible(timeout=2000):
            log("[AIS] AIS generation queued — Go To Activity History button visible.")
            await _close_modal(portal, log)
            return {"status": "requested", "ref_id": ref_id, "fy": fiscal_year}

        log("[AIS] Unknown state after clicking Download — check portal manually.")
        await _close_modal(portal, log)
        return {"status": "failed"}

    except Exception as e:
        log(f"[AIS] Request failed: {e}")
        await _close_modal(portal, log)
        return {"status": "failed"}


# ── AIS Download from Activity History ───────────────────────────────────────

async def download_ais_from_activity_history(portal: Page, fiscal_year: str,
                                              download_dir: str, log,
                                              pan: str = "",
                                              ref_id: str = "") -> bool:
    """
    Navigate to Activity History and download the AIS PDF for the given FY.
    Matches by Reference ID if provided, otherwise by Description = "AIS - F.Y. XXXX-XX".

    The row appears immediately after requesting but shows a spinner while generating.
    We poll every 30s (up to 10 min) until the download icon replaces the spinner.
    """
    os.makedirs(download_dir, exist_ok=True)
    fy_str = fiscal_year.replace("-", "_")
    prefix = f"{pan}-" if pan else ""
    ais_file = os.path.join(download_dir, f"{prefix}AIS-{fy_str}.pdf")

    log("[AIS] Navigating to Activity History...")
    await update_browser_status(portal, "AIS: Opening Activity History...")

    try:
        act_link = portal.locator(
            "a:has-text('Activity History'), "
            "li:has-text('Activity History') a, "
            "nav a:has-text('Activity')"
        ).first
        await act_link.wait_for(state="visible", timeout=10000)
        await act_link.click()
        await portal.wait_for_load_state("domcontentloaded", timeout=20000)
        await asyncio.sleep(2)
        log(f"[AIS] Activity History loaded: {portal.url}")
    except Exception as e:
        log(f"[AIS] Could not navigate to Activity History: {e}")
        return False

    fy_desc = f"AIS - F.Y. {fiscal_year}"

    # ── Poll until download icon is ready (spinner → ⬇) ─────────────────────
    # Max 20 attempts × 30s = 10 minutes
    MAX_ATTEMPTS = 20
    POLL_INTERVAL = 30  # seconds

    for attempt in range(MAX_ATTEMPTS):
        # Reload page to get latest status
        if attempt > 0:
            log(f"[AIS] File still generating... ({attempt}/{MAX_ATTEMPTS-1}, "
                f"retrying in {POLL_INTERVAL}s)")
            await update_browser_status(portal, f"AIS: Waiting for generation "
                                                f"({attempt}/{MAX_ATTEMPTS-1})...")
            await asyncio.sleep(POLL_INTERVAL)
            try:
                await portal.reload(wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(2)
            except Exception:
                pass

        try:
            # Locate the row
            if ref_id:
                row = portal.locator(f"tr:has-text('{ref_id}')").first
            else:
                row = portal.locator(
                    f"tr:has-text('AIS Downloaded - PDF'):has-text('{fy_desc}')"
                ).first

            await row.wait_for(state="visible", timeout=8000)

            # Check if download icon is present (not a spinner)
            # Spinner is typically mat-spinner, .spinner, or similar animated element
            # Download icon is a button/anchor — if spinner is present the dl button won't be
            spinner = row.locator(
                "mat-spinner, .spinner, [class*='spinner'], "
                "[class*='loading'], circle[class*='path']"
            ).first
            try:
                is_spinning = await spinner.is_visible(timeout=1000)
            except Exception:
                is_spinning = False

            if is_spinning:
                continue  # Still generating — loop again

            # Check for a clickable download icon
            dl_icon = row.locator(
                "button:not([disabled]), a:not([disabled])"
            ).filter(
                has=portal.locator(
                    "[class*='download'], mat-icon:has-text('download'), "
                    "[title*='download' i], [aria-label*='download' i]"
                )
            ).first

            try:
                is_ready = await dl_icon.is_visible(timeout=1000)
            except Exception:
                is_ready = False
            if not is_ready:
                # Fallback: any enabled button in row that isn't a text/expand button
                dl_icon = row.locator("button").last
                try:
                    is_ready = await dl_icon.is_visible(timeout=1000)
                except Exception:
                    is_ready = False

            if is_ready:
                log("[AIS] AIS file ready. Downloading...")
                await update_browser_status(portal, "AIS: Downloading from Activity History...")
                async with portal.context.expect_download(timeout=60000) as dl_info:
                    await dl_icon.click()
                download = await dl_info.value
                await download.save_as(ais_file)
                log(f"[Victory] AIS PDF saved: {os.path.basename(ais_file)}")
                return True

        except Exception as e:
            if attempt == 0:
                log(f"[AIS] Row not found yet: {e}")
            continue

    log("[Warning] AIS generation timed out after 10 minutes. "
        "Try 'Download AIS/TIS' again later.")
    return False


# ── Top-level entry points (called from app.py) ───────────────────────────────

async def run_request_ais(itd_page: Page, fiscal_year: str, download_dir: str,
                          log, pan: str = "") -> dict:
    """
    Phase 1 — Called from 'Request AIS' button.
    Opens portal, navigates to AIS tab, selects FY, requests AIS PDF generation.
    Returns result dict from request_ais().
    """
    fy_start = int(fiscal_year.split("-")[0]) if "-" in fiscal_year else 0
    if fy_start < 2021:
        log(f"[AIS] Skipping — AIS not available before FY 2021-22.")
        return {"status": "skipped"}

    portal = None
    try:
        portal = await _open_ais_portal(itd_page, log)
        await _navigate_to_ais_tab(portal, log)
        await _select_fy(portal, fiscal_year, log)
        result = await request_ais(portal, fiscal_year, download_dir, log, pan=pan)
        await portal.close()
        return result
    except Exception as e:
        log(f"[AIS] Request phase failed: {e}")
        if portal:
            try: await portal.close()
            except Exception: pass
        return {"status": "failed"}


async def run_download_ais_tis(itd_page: Page, fiscal_year: str, download_dir: str,
                               log, pan: str = "",
                               dl_ais: bool = True, dl_tis: bool = True,
                               ais_ref_id: str = "") -> bool:
    """
    Phase 2 — Called from 'Download AIS/TIS' button.
    Downloads TIS instantly and AIS PDF from Activity History.
    """
    fy_start = int(fiscal_year.split("-")[0]) if "-" in fiscal_year else 0
    if fy_start < 2021:
        log(f"[AIS/TIS] Skipping — not available before FY 2021-22.")
        return True

    portal = None
    success = True
    try:
        portal = await _open_ais_portal(itd_page, log)
        await _navigate_to_ais_tab(portal, log)
        await _select_fy(portal, fiscal_year, log)

        if dl_tis:
            ok = await download_tis(portal, fiscal_year, download_dir, log, pan=pan)
            if not ok:
                log("[Warning] TIS download failed.")
                success = False

        if dl_ais:
            fy_str = fiscal_year.replace("-", "_")
            prefix = f"{pan}-" if pan else ""
            ais_file = os.path.join(download_dir, f"{prefix}AIS-{fy_str}.pdf")

            if os.path.exists(ais_file):
                # Already downloaded instantly during Request AIS — nothing to do
                log(f"[AIS] AIS PDF already present (instant download): "
                    f"{os.path.basename(ais_file)} — skipping Activity History.")
            else:
                # Large file — fetch from Activity History
                ok = await download_ais_from_activity_history(
                    portal, fiscal_year, download_dir, log,
                    pan=pan, ref_id=ais_ref_id)
                if not ok:
                    log("[Warning] AIS PDF not found in Activity History. "
                        "Try 'Request AIS' first if you haven't already.")
                    success = False

        await portal.close()
        return success
    except Exception as e:
        log(f"[AIS/TIS] Download phase failed: {e}")
        if portal:
            try: await portal.close()
            except Exception: pass
        return False
