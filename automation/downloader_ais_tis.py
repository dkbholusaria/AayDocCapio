import os
import re
import asyncio
from playwright.async_api import Page
from automation.downloader import update_browser_status, make_step_logger

# ── Navigation ────────────────────────────────────────────────────────────────

async def _open_hamburger(itd_page: Page, log):
    """
    The ITD dashboard collapses the nav into a hamburger (☰ = #hamburgerOpen).
    a#AIS exists in the DOM but is only clickable once the hamburger panel is
    open. The page may also be scrolled down, hiding the nav bar — scroll to
    top first so the hamburger/nav is in view.
    """
    step = make_step_logger(log, "NAV")
    # Scroll everything to top — window AND any scrollable containers.
    try:
        step("Scrolling page to top", itd_page)
        await itd_page.evaluate("""() => {
            window.scrollTo(0, 0);
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
            document.querySelectorAll('*').forEach(el => {
                if (el.scrollTop > 0) el.scrollTop = 0;
            });
        }""")
        await asyncio.sleep(0.5)
    except Exception as e:
        step(f"Scroll failed: {e}")

    for sel in (
        "#hamburgerOpen",
        "button[aria-label*='main menu' i]",
        "button[aria-label*='menu' i]",
        "[role='button'][aria-label*='menu' i]",
        ".hamburger",
    ):
        try:
            btn = itd_page.locator(sel).first
            cnt = await btn.count()
            step(f"Probing hamburger selector '{sel}' — count={cnt}")
            if cnt == 0:
                continue
            try:
                await btn.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            vis = await btn.is_visible(timeout=500)
            step(f"  '{sel}' visible={vis}")
            if vis:
                step(f"Clicking hamburger '{sel}'")
                try:
                    await btn.click(timeout=3000)
                except Exception:
                    await btn.click(force=True, timeout=3000)
                await asyncio.sleep(1)
                step("Hamburger clicked")
                return
        except Exception as e:
            step(f"  selector '{sel}' error: {e}")
            continue

    step("No hamburger button matched — nav may already be expanded")


async def _open_ais_portal(itd_page: Page, log) -> Page:
    """
    From the ITD dashboard, click the AIS nav link to open the Compliance Portal.
    Mirrors the competitor: open hamburger, click a#AIS, dismiss any "Yes"
    confirmation, then race between a new tab opening and the same tab
    navigating to ais.insight.gov.in.
    Returns the compliance portal Page.
    """
    step = make_step_logger(log, "AIS-OPEN")
    step("Starting Compliance Portal open", itd_page)
    await update_browser_status(itd_page, "AIS: Opening Compliance Portal...")

    step("Opening hamburger / nav menu")
    await _open_hamburger(itd_page, log)

    ais_link = itd_page.locator("a#AIS").first
    step("Waiting for a#AIS to be visible")
    try:
        await ais_link.wait_for(state="visible", timeout=15000)
        step("a#AIS is visible")
    except Exception:
        step("a#AIS NOT visible after 15s — dumping not available, raising")
        raise Exception("AIS nav link not found on ITD dashboard.")

    # Set up the new-tab listener BEFORE clicking.
    step("Arming new-tab listener")
    new_page_task = asyncio.ensure_future(
        itd_page.context.wait_for_event("page", timeout=15000))

    step("Clicking a#AIS")
    try:
        await ais_link.click(timeout=10000)
        step("a#AIS click sent")
    except Exception as e:
        step(f"normal click failed ({e}) — trying force click")
        await ais_link.click(force=True, timeout=10000)

    # Optional "Yes" confirmation dialog before the portal opens.
    try:
        yes = itd_page.get_by_role("button", name=re.compile(r"^yes$", re.I)).first
        if await yes.is_visible(timeout=1000):
            step("'Yes' confirmation dialog detected — confirming")
            try:
                await yes.click(timeout=5000)
            except Exception:
                await yes.click(force=True, timeout=5000)
        else:
            step("No 'Yes' confirmation dialog")
    except Exception:
        step("No 'Yes' confirmation dialog")

    # Race: new tab opens, OR same tab navigates to the Insight portal.
    portal = None
    step("Waiting for portal (new tab OR same-tab URL change)")
    try:
        portal = await new_page_task
        step("Portal opened in a NEW tab", portal)
    except Exception:
        new_page_task.cancel()
        step("No new tab — checking same-tab navigation to insight.gov.in")
        try:
            await itd_page.wait_for_url(re.compile(r"ais\.insight\.gov\.in", re.I),
                                        timeout=15000)
            portal = itd_page
            step("Portal opened in SAME tab", portal)
        except Exception:
            portal = itd_page
            step("Portal did NOT open — still on original page", portal)

    try:
        await portal.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass

    step("Compliance Portal ready", portal)
    await asyncio.sleep(3)  # Angular SPA hydration
    await update_browser_status(portal, "AIS: Compliance Portal ready")
    return portal


async def _navigate_to_ais_tab(portal: Page, log):
    """
    Wait for AIS portal to load. Stay on instructions page —
    the 'Download AIS/TIS' shortcut button here is what initializes
    the Angular dialog correctly.
    """
    step = make_step_logger(log, "AIS-NAV")
    step("Waiting for AIS portal networkidle", portal)
    try:
        await portal.wait_for_load_state("networkidle", timeout=20000)
    except Exception as e:
        step(f"networkidle wait failed: {e}")
    await asyncio.sleep(2)
    step("AIS portal ready", portal)
    await update_browser_status(portal, "AIS: Portal ready")


async def _select_fy(portal: Page, fiscal_year: str, log):
    """
    Select FY by going to /ais/home, using the dropdown, then coming back
    to instructions page so the shortcut button reflects the correct FY.
    If the shortcut button already shows the right FY, nothing to do.
    """
    step = make_step_logger(log, "AIS-FY")
    step(f"Checking F.Y. {fiscal_year}", portal)

    # Check if instructions page shortcut button already shows right FY
    try:
        btn_text = await portal.locator(
            "button:has-text('Download AIS/TIS')"
        ).first.inner_text(timeout=5000)
        step(f"Shortcut button text: '{btn_text.strip()}'")
        if fiscal_year in btn_text:
            step(f"F.Y. {fiscal_year} already set — no switch needed")
            return
    except Exception as e:
        step(f"Could not read shortcut button text: {e}")

    # Switch to AIS home, change FY, come back to instructions
    step(f"Switching FY to {fiscal_year} via AIS home")
    try:
        ais_tab = portal.locator("nav.sub-navbar a").nth(1)
        step("Waiting for AIS sub-nav tab")
        await ais_tab.wait_for(state="visible", timeout=5000)
        step("Clicking AIS sub-nav tab")
        await ais_tab.click()
        await asyncio.sleep(2)

        toggle = portal.locator(".fy-dropdown button#dropdownMenuButton").first
        step("Waiting for FY dropdown toggle", portal)
        await toggle.wait_for(state="visible", timeout=8000)
        current = (await toggle.inner_text()).strip()
        step(f"Current FY dropdown value: '{current}'")
        if fiscal_year not in current:
            step("Opening FY dropdown")
            await toggle.click()
            await asyncio.sleep(0.5)
            option = portal.locator(
                f".fy-dropdown button.dropdown-item:has-text('F.Y. {fiscal_year}')"
            ).first
            step(f"Selecting 'F.Y. {fiscal_year}' option")
            await option.wait_for(state="visible", timeout=5000)
            await option.click()
            await asyncio.sleep(1)
            step(f"F.Y. {fiscal_year} selected")

        # Navigate back to instructions page
        step("Navigating back to Instructions tab")
        instr_tab = portal.locator("nav.sub-navbar a").nth(0)
        await instr_tab.click()
        await asyncio.sleep(1.5)
        step("Back on instructions", portal)
    except Exception as e:
        step(f"Could not switch F.Y.: {e}")


async def _open_download_modal(portal: Page, log, label: str) -> bool:
    """Click the 'Download AIS/TIS' shortcut button on instructions page."""
    step = make_step_logger(log, f"{label}-MODAL")
    try:
        btn = portal.locator("button:has-text('Download AIS/TIS')").first
        step("Waiting for 'Download AIS/TIS' shortcut button", portal)
        await btn.wait_for(state="visible", timeout=10000)
        step("Clicking 'Download AIS/TIS' button")
        await btn.click(timeout=10000)
        await asyncio.sleep(1)
        modal = portal.locator("mat-dialog-container").first
        vis = await modal.is_visible(timeout=3000)
        step(f"Modal visible after click: {vis}")
        return bool(vis)
    except Exception as e:
        step(f"Could not open modal: {e}")
        return False


async def _open_tis_modal(portal: Page, log) -> bool:
    return await _open_download_modal(portal, log, "TIS")


async def _open_ais_modal(portal: Page, log) -> bool:
    return await _open_download_modal(portal, log, "AIS")


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

    tis_file = os.path.join(download_dir, f"{prefix}TIS-{fy_str}.pdf")

    # If a modal is already open from the AIS step and it contains a TIS row,
    # use it directly; otherwise open the shortcut modal.
    modal = _modal_locator(portal)
    try:
        modal_open = await modal.is_visible(timeout=1000)
    except Exception:
        modal_open = False

    has_tis_row = False
    if modal_open:
        try:
            has_tis_row = await modal.locator(
                "p.dialog-sub-head:has-text('Taxpayer Information Summary (TIS) - PDF')"
            ).first.is_visible(timeout=1000)
        except Exception:
            has_tis_row = False

    if not has_tis_row:
        opened = await _open_tis_modal(portal, log)
        if not opened:
            return False
        modal = _modal_locator(portal)
        try:
            await modal.wait_for(state="visible", timeout=5000)
        except Exception:
            log("[TIS] Modal did not appear.")
            return False

    await update_browser_status(portal, "AIS: Downloading TIS PDF...")
    ok = await _download_modal_row(
        portal,
        "Taxpayer Information Summary (TIS) - PDF",
        tis_file, log, "TIS")
    await _close_modal(portal, log)
    return ok


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

    step = make_step_logger(log, "AIS-DL")
    try:
        # AIS PDF row: first button.dialog-outline-btn in the modal
        dl_btn = modal.locator("button.dialog-outline-btn").first
        cnt = await modal.locator("button.dialog-outline-btn").count()
        step(f"Found {cnt} download button(s) in modal")
        await dl_btn.wait_for(state="visible", timeout=5000)
        step("AIS PDF Download button visible")
        await update_browser_status(portal, "AIS: Requesting AIS PDF...")

        # Track whether the download API actually fires
        api_hit = {}
        async def _on_resp(r):
            if "ais-details-pdf" in r.url:
                api_hit["status"] = r.status
        portal.on("response", _on_resp)

        # Competitor's approach: set up download listener, plain click,
        # then click any OK confirmation that appears.
        try:
            async with portal.expect_download(timeout=60000) as dl_info:
                step("Clicking AIS PDF Download button")
                await dl_btn.click(timeout=10000)
                step("Click sent; waiting for download…")
                await asyncio.sleep(0.5)
                ok = portal.get_by_role("button", name=_re.compile(r"^ok$", _re.I)).first
                try:
                    if await ok.is_visible(timeout=1500):
                        step("OK confirmation found — clicking")
                        await ok.click(timeout=5000)
                except Exception:
                    pass
            download = await dl_info.value
            portal.remove_listener("response", _on_resp)
            await download.save_as(ais_file)
            step(f"Download saved: {os.path.basename(ais_file)}")
            log(f"[Victory] AIS PDF downloaded: {os.path.basename(ais_file)}")
            await _close_modal(portal, log)
            return {"status": "downloaded", "file": ais_file}
        except Exception as dl_e:
            portal.remove_listener("response", _on_resp)
            if api_hit:
                step(f"No file download, but API was hit (status={api_hit.get('status')}) — large file queued")
            else:
                step(f"No download AND API never fired — click likely did not register ({dl_e})")

        # Large-file path: modal shows success / Activity History message
        await asyncio.sleep(2)
        try:
            modal_text = await modal.inner_text()
        except Exception:
            modal_text = ""

        ref_match = _re.search(r'Reference\s*(?:ID|No\.?)[:\s]*([A-Z0-9\-]+)', modal_text, _re.IGNORECASE)
        ref_id = ref_match.group(1).strip() if ref_match else ""

        log(f"[AIS] AIS generation queued. Reference ID: {ref_id or 'N/A'}")
        await _close_modal(portal, log)
        return {"status": "requested", "ref_id": ref_id, "fy": fiscal_year}

    except Exception as e:
        log(f"[AIS] Request failed: {e}")
        await _close_modal(portal, log)
        return {"status": "failed"}


async def _download_modal_row(portal: Page, row_text: str, save_path: str,
                              log, label: str) -> bool:
    """
    In the currently-open download modal, click the Download button on the row
    whose dialog-sub-head matches `row_text`, and save the file to `save_path`.
    Returns True on success.
    """
    step = make_step_logger(log, f"{label}-DL")
    modal = _modal_locator(portal)
    try:
        row = modal.locator(
            f"div.d-flex:has(p.dialog-sub-head:has-text('{row_text}'))"
        ).first
        dl_btn = row.locator("button.dialog-outline-btn").first
        step(f"Waiting for '{row_text}' Download button")
        await dl_btn.wait_for(state="visible", timeout=5000)
        step("Clicking Download")
        async with portal.expect_download(timeout=60000) as dl_info:
            await dl_btn.click(timeout=10000)
            await asyncio.sleep(0.5)
        download = await dl_info.value
        await download.save_as(save_path)
        step(f"Saved: {os.path.basename(save_path)}")
        log(f"[Victory] {label} PDF downloaded: {os.path.basename(save_path)}")
        return True
    except Exception as e:
        step(f"Download failed: {e}")
        return False


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
                async with portal.expect_download(timeout=60000) as dl_info:
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

        # AIS PDF (instant download or queued request)
        result = await request_ais(portal, fiscal_year, download_dir, log, pan=pan)

        # TIS PDF — always instant, lives in its own modal. Attempt it too so
        # 'Download / Request TIS & AIS' fetches both in one pass.
        try:
            tis_ok = await download_tis(portal, fiscal_year, download_dir, log, pan=pan)
            result["tis"] = "downloaded" if tis_ok else "failed"
        except Exception as te:
            log(f"[TIS] TIS download error: {te}")
            result["tis"] = "failed"

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
