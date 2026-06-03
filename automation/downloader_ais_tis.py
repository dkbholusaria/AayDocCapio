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
    Wait for AIS portal to load. Stay on instructions page —
    the 'Download AIS/TIS' shortcut button here is what initializes
    the Angular dialog correctly.
    """
    log("[AIS] Waiting for AIS portal to load...")
    await portal.wait_for_load_state("networkidle", timeout=20000)
    await asyncio.sleep(2)
    log(f"[AIS] Portal ready. URL: {portal.url}")
    await update_browser_status(portal, "AIS: Portal ready")


async def _select_fy(portal: Page, fiscal_year: str, log):
    """
    Select FY by going to /ais/home, using the dropdown, then coming back
    to instructions page so the shortcut button reflects the correct FY.
    If the shortcut button already shows the right FY, nothing to do.
    """
    log(f"[AIS] Checking F.Y. {fiscal_year}...")

    # Check if instructions page shortcut button already shows right FY
    try:
        btn_text = await portal.locator(
            "button:has-text('Download AIS/TIS')"
        ).first.inner_text(timeout=5000)
        if fiscal_year in btn_text:
            log(f"[AIS] F.Y. {fiscal_year} already set.")
            return
    except Exception:
        pass

    # Switch to AIS home, change FY, come back to instructions
    log(f"[AIS] Switching FY to {fiscal_year}...")
    try:
        ais_tab = portal.locator("nav.sub-navbar a").nth(1)
        await ais_tab.wait_for(state="visible", timeout=5000)
        await ais_tab.click()
        await asyncio.sleep(2)

        toggle = portal.locator(".fy-dropdown button#dropdownMenuButton").first
        await toggle.wait_for(state="visible", timeout=8000)
        current = (await toggle.inner_text()).strip()
        if fiscal_year not in current:
            await toggle.click()
            await asyncio.sleep(0.5)
            option = portal.locator(
                f".fy-dropdown button.dropdown-item:has-text('F.Y. {fiscal_year}')"
            ).first
            await option.wait_for(state="visible", timeout=5000)
            await option.click()
            await asyncio.sleep(1)
            log(f"[AIS] F.Y. {fiscal_year} selected.")

        # Navigate back to instructions page
        instr_tab = portal.locator("nav.sub-navbar a").nth(0)
        await instr_tab.click()
        await asyncio.sleep(1.5)
        log(f"[AIS] Back on instructions. URL: {portal.url}")
    except Exception as e:
        log(f"[Warning] Could not switch F.Y.: {e}")


async def _open_tis_modal(portal: Page, log) -> bool:
    """Click the 'Download AIS/TIS' shortcut button on instructions page."""
    log("[TIS] Opening download modal via shortcut button...")
    try:
        btn = portal.locator("button:has-text('Download AIS/TIS')").first
        await btn.wait_for(state="visible", timeout=10000)
        await btn.click(timeout=10000)
        await asyncio.sleep(1)
        modal = portal.locator("mat-dialog-container").first
        if await modal.is_visible(timeout=3000):
            log("[TIS] Modal opened.")
            return True
        log("[TIS] Modal did not open.")
        return False
    except Exception as e:
        log(f"[TIS] Could not open modal: {e}")
        return False


async def _open_ais_modal(portal: Page, log) -> bool:
    """Click the 'Download AIS/TIS' shortcut button on instructions page."""
    log("[AIS] Opening download modal via shortcut button...")
    try:
        btn = portal.locator("button:has-text('Download AIS/TIS')").first
        await btn.wait_for(state="visible", timeout=10000)
        await btn.click(timeout=10000)
        await asyncio.sleep(1)
        modal = portal.locator("mat-dialog-container").first
        if await modal.is_visible(timeout=3000):
            log("[AIS] Modal opened.")
            return True
        log("[AIS] Modal did not open.")
        return False
    except Exception as e:
        log(f"[AIS] Could not open modal: {e}")
        return False


def _modal_locator(portal: Page):
    """Return a locator for the open Download modal."""
    return portal.locator("mat-dialog-container").first


async def _close_modal(portal: Page, log):
    """Close the modal via the close icon (img[alt='Close'])."""
    try:
        modal = _modal_locator(portal)
        close_btn = modal.locator("img[alt='Close']").first
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

    # Modal row: p.dialog-sub-head "Taxpayer Information Summary (TIS) - PDF" + button.dialog-outline-btn
    tis_file = os.path.join(download_dir, f"{prefix}TIS-{fy_str}.pdf")
    try:
        log("[TIS] Downloading TIS PDF...")
        await update_browser_status(portal, "AIS: Downloading TIS PDF...")
        dl_btn = modal.get_by_role("button", name="Download").first
        await dl_btn.wait_for(state="visible", timeout=8000)

        async with portal.context.expect_download(timeout=60000) as dl_info:
            await dl_btn.click()
            await asyncio.sleep(0.5)
            ok_btn = modal.get_by_role("button", name="OK").first
            try:
                if await ok_btn.is_visible(timeout=1000):
                    await ok_btn.click(timeout=5000)
            except Exception:
                pass

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
    Click Download on the AIS PDF row in the modal.
    Two outcomes:
      - Instant download → file saved, returns {"status": "downloaded"}
      - Queued (large file) → button changes / success message appears,
        returns {"status": "requested", "ref_id": "..."}
    """
    import re as _re
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

    try:
        # Debug: dump all buttons in modal
        btns = await portal.evaluate("""() => {
            const btns = document.querySelectorAll('mat-dialog-container button');
            return [...btns].map(b => ({text: b.innerText.trim(), class: b.className}));
        }""")
        log(f"[DEBUG] Modal buttons: {btns}")

        dl_btn = modal.locator("button.dialog-outline-btn").first
        await dl_btn.wait_for(state="visible", timeout=5000)

        log("[AIS] Clicking Download for AIS PDF...")
        await update_browser_status(portal, "AIS: Requesting AIS PDF...")

        # Intercept response to confirm API fires
        api_fired = {}
        async def on_resp(r):
            if "ais-details-pdf" in r.url or "tis-details" in r.url:
                api_fired["url"] = r.url
        portal.on("response", on_resp)

        # Click without expect_download wrapper — check if API fires without it
        await dl_btn.click(timeout=10000)
        await asyncio.sleep(3)

        portal.remove_listener("response", on_resp)
        if api_fired:
            log(f"[DEBUG] API fired: {api_fired['url']}")
        else:
            log("[DEBUG] API did NOT fire after plain click")

        # Wait for modal to update with success/queued state
        await asyncio.sleep(2)
        try:
            modal_text = await modal.inner_text()
        except Exception:
            modal_text = ""


        # Extract Reference ID if present
        ref_match = _re.search(r'Reference\s*(?:ID|No\.?)[:\s]*([A-Z0-9\-]+)', modal_text, _re.IGNORECASE)
        ref_id = ref_match.group(1).strip() if ref_match else ""

        # Detect queued state: "Go To Activity History" button or success text
        try:
            goto_visible = await modal.locator(
                "button:has-text('Go To Activity History')"
            ).first.is_visible(timeout=2000)
        except Exception:
            goto_visible = False

        queued = (goto_visible
                  or ref_id
                  or "activity history" in modal_text.lower()
                  or "submitted successfully" in modal_text.lower())

        if queued:
            log(f"[AIS] AIS generation queued. Reference ID: {ref_id or 'N/A'}")
            await _close_modal(portal, log)
            return {"status": "requested", "ref_id": ref_id, "fy": fiscal_year}

        # Modal unchanged = button fired but portal queued the request silently
        # (large file case — no modal update, no instant download)
        # Treat as requested since the click was sent successfully
        log("[AIS] AIS request sent — treating as queued (no instant download).")
        await _close_modal(portal, log)
        return {"status": "requested", "ref_id": "", "fy": fiscal_year}

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

    Row structure (from actual portal HTML):
      - Main rows: tr.example-element-row
      - Activity column: td.mat-column-activityType span  → "AIS Downloaded - PDF"
      - Description column: td.mat-column-description span → "AIS - F.Y. 2025-26"
      - Reference ID column: td.mat-column-referenceId span → "406202603001101"
      - Download column: td.mat-column-download
          Pending:  a > img[alt="Progress"][title="File in progress"]
          Ready:    a[title="Download file"] > img[alt="Download"]
    """
    os.makedirs(download_dir, exist_ok=True)
    fy_str = fiscal_year.replace("-", "_")
    prefix = f"{pan}-" if pan else ""
    ais_file = os.path.join(download_dir, f"{prefix}AIS-{fy_str}.pdf")
    fy_desc = f"AIS - F.Y. {fiscal_year}"

    log("[AIS] Navigating to Activity History...")
    await update_browser_status(portal, "AIS: Opening Activity History...")

    try:
        act_link = portal.locator("nav.ctm-navbar li.item a:has-text('Activity History')").first
        await act_link.wait_for(state="visible", timeout=10000)
        await act_link.click()
        await portal.wait_for_load_state("domcontentloaded", timeout=20000)
        await asyncio.sleep(2)
        log(f"[AIS] Activity History loaded: {portal.url}")
    except Exception as e:
        log(f"[AIS] Could not navigate to Activity History: {e}")
        return False

    MAX_ATTEMPTS = 20
    POLL_INTERVAL = 30

    for attempt in range(MAX_ATTEMPTS):
        if attempt > 0:
            log(f"[AIS] Still generating... (attempt {attempt}/{MAX_ATTEMPTS-1}, "
                f"waiting {POLL_INTERVAL}s)")
            await update_browser_status(
                portal, f"AIS: Waiting for generation ({attempt}/{MAX_ATTEMPTS-1})...")
            await asyncio.sleep(POLL_INTERVAL)
            try:
                await portal.reload(wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(2)
            except Exception:
                pass

        try:
            # Find the matching row — prefer ref_id match, fall back to FY description
            if ref_id:
                row = portal.locator(
                    f"tr.example-element-row:has(td.mat-column-referenceId:has-text('{ref_id}'))"
                ).first
            else:
                row = portal.locator(
                    f"tr.example-element-row"
                    f":has(td.mat-column-activityType:has-text('AIS Downloaded - PDF'))"
                    f":has(td.mat-column-description:has-text('{fy_desc}'))"
                ).first

            await row.wait_for(state="visible", timeout=5000)

            dl_cell = row.locator("td.mat-column-download").first

            # In-progress: img[alt="Progress"]
            try:
                progress_img = dl_cell.locator("img[alt='Progress']").first
                is_pending = await progress_img.is_visible(timeout=500)
            except Exception:
                is_pending = False

            if is_pending:
                log(f"[AIS] File still generating (attempt {attempt+1})...")
                continue

            # Ready: a[title="Download file"]
            try:
                dl_link = dl_cell.locator("a[title='Download file']").first
                is_ready = await dl_link.is_visible(timeout=500)
            except Exception:
                is_ready = False

            if is_ready:
                log("[AIS] File ready — downloading...")
                await update_browser_status(portal, "AIS: Downloading from Activity History...")
                async with portal.context.expect_download(timeout=60000) as dl_info:
                    await dl_link.click()
                download = await dl_info.value
                await download.save_as(ais_file)
                log(f"[Victory] AIS PDF saved: {os.path.basename(ais_file)}")
                return True

            log(f"[AIS] Row found but no download link yet (attempt {attempt+1}).")

        except Exception as e:
            if attempt == 0:
                log(f"[AIS] Row not found yet: {e}")

    log("[Warning] AIS generation timed out after 10 minutes.")
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
