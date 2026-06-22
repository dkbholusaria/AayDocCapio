import os
import re
import asyncio
from playwright.async_api import Page
from automation.downloader import update_browser_status, make_step_logger
from automation.pdf_unlocker import unlock_pdf


# ── Outcome helpers ───────────────────────────────────────────────────────────

def _outcome(status: str, unlocked=None, reason: str = None, **extra) -> dict:
    """Create a standard document-outcome dict."""
    d = {"status": status, "unlocked": unlocked, "reason": reason}
    d.update(extra)
    return d


def _doc_label(o: dict | None, name: str) -> str | None:
    """Turn a single document outcome into a short UI label."""
    if not o:
        return None
    s = o.get("status", "")
    u = o.get("unlocked")
    if s == "downloaded":
        if u is True:  return f"✅ {name} unlocked"
        if u is False: return f"⚠️ {name} locked — wrong password"
        return f"✅ {name} downloaded"
    if s == "already_present": return f"✅ {name} already present"
    if s == "requested":       return f"🕐 {name} queued"
    if s == "too_large":       return f"⚠️ {name} too large — use AIS Utility"
    if s == "no_data":         return f"⬜ {name} — no data for this FY"
    if s == "not_found":       return f"⬜ {name} not in Activity History"
    if s == "timeout":         return f"🕐 {name} still generating — try again"
    if s == "aborted":         return f"⏹ {name} aborted"
    if s == "skipped":         return f"⬜ {name} skipped"
    if s == "failed":          return f"❌ {name} failed"
    return None


def combined_status_label(ais_o: dict | None, tis_o: dict | None) -> str:
    """Build a combined AIS + TIS status label for the batch grid."""
    parts = [l for l in (_doc_label(ais_o, "AIS"), _doc_label(tis_o, "TIS")) if l]
    return " | ".join(parts) if parts else "—"


def _unlock_and_warn(file_path, pan, dob, log, label="PDF", status_cb=None):
    """Unlock PDF and emit a clear [Warning] if no password matched."""
    if status_cb:
        status_cb(f"🔓 Unlocking {label}…")
    result = unlock_pdf(file_path, pan=pan, dob=dob, log=log)
    if result.get("unlocked"):
        if status_cb:
            status_cb(f"✅ {label} downloaded & unlocked")
    else:
        reason = result.get("reason", "unknown")
        if reason == "no-password-matched":
            log(
                f"[Warning] {label} unlock failed — no password candidate matched "
                f"{os.path.basename(file_path)}. "
                f"Verify DOB in vault matches PAN card exactly (used: {dob or 'none'})."
            )
            if status_cb:
                status_cb(f"⚠️ {label} downloaded — PDF unlock failed (wrong password?)")
        elif reason == "no-dob":
            log(f"[Warning] {label} unlock skipped — no DOB stored in vault for this client.")
            if status_cb:
                status_cb(f"⚠️ {label} downloaded — no DOB in vault, PDF still locked")
    return result


async def _wait_for_download(page: Page, timeout: int = 120000):
    """
    Await a single download on `page` and return the Download object.
    Used as a background task so the caller can race it against the
    large-file "queued" message. Returns None if no download arrives.
    """
    try:
        async with page.expect_download(timeout=timeout) as dl_info:
            pass
        return await dl_info.value
    except Exception:
        return None


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


async def _open_ais_portal(itd_page: Page, log, status_cb=None) -> Page:
    """
    From the ITD dashboard, click the AIS nav link to open the Compliance Portal.
    Mirrors the competitor: open hamburger, click a#AIS, dismiss any "Yes"
    confirmation, then race between a new tab opening and the same tab
    navigating to ais.insight.gov.in.
    Returns the compliance portal Page.
    """
    step = make_step_logger(log, "AIS-OPEN", status_cb=status_cb)
    step("Starting Compliance Portal open", itd_page, status="Opening Compliance Portal…")
    await update_browser_status(itd_page, "AIS: Opening Compliance Portal...")

    # Wait for any loading overlay to clear FIRST — overlay makes a#AIS invisible to Playwright.
    try:
        step("Waiting for loader overlay to clear…")
        await itd_page.locator(".customLoaderBackdrop").wait_for(state="hidden", timeout=30000)
        step("Loader overlay gone")
    except Exception:
        step("No loader overlay detected (or already gone)")

    step("Opening hamburger / nav menu")
    await _open_hamburger(itd_page, log)

    ais_link = itd_page.locator("a#AIS").first
    step("Waiting for a#AIS to be visible", status="Finding AIS menu…")
    try:
        await ais_link.wait_for(state="visible", timeout=30000)
        step("a#AIS is visible")
    except Exception:
        step("a#AIS NOT visible after 30s — raising")
        raise Exception("AIS nav link not found on ITD dashboard.")

    # Set up the new-tab listener BEFORE clicking.
    step("Arming new-tab listener")
    new_page_task = asyncio.ensure_future(
        itd_page.context.wait_for_event("page", timeout=30000))

    step("Clicking a#AIS", status="Opening AIS portal…")
    try:
        await ais_link.click(timeout=20000)
        step("a#AIS click sent")
    except Exception as e:
        step(f"normal click failed ({e}) — trying force click")
        await ais_link.click(force=True, timeout=20000)

    # Optional "Yes" confirmation dialog before the portal opens.
    try:
        yes = itd_page.get_by_role("button", name=re.compile(r"^yes$", re.I)).first
        if await yes.is_visible(timeout=1000):
            step("'Yes' confirmation dialog detected — confirming")
            try:
                await yes.click(timeout=10000)
            except Exception:
                await yes.click(force=True, timeout=10000)
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
                                        timeout=30000)
            portal = itd_page
            step("Portal opened in SAME tab", portal)
        except Exception:
            portal = itd_page
            step("Portal did NOT open — still on original page", portal)

    try:
        await portal.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass

    step("Compliance Portal ready", portal, status="AIS portal ready")
    await asyncio.sleep(3)  # Angular SPA hydration
    await update_browser_status(portal, "AIS: Compliance Portal ready")
    return portal


async def _navigate_to_ais_tab(portal: Page, log, status_cb=None):
    """
    Wait for AIS portal to load (networkidle).
    """
    step = make_step_logger(log, "AIS-NAV", status_cb=status_cb)
    step("Waiting for AIS portal networkidle", portal, status="Loading AIS portal…")
    try:
        await portal.wait_for_load_state("networkidle", timeout=40000)
    except Exception as e:
        step(f"networkidle wait failed: {e}")
    await asyncio.sleep(2)
    step("AIS portal ready", portal)
    await update_browser_status(portal, "AIS: Portal ready")


async def _select_fy(portal: Page, fiscal_year: str, log, status_cb=None):
    """
    Select the correct FY via the AIS home tab dropdown.
    Stays on the AIS home tab so the 'Download AIS/TIS' button
    is scoped to the selected FY (the Instructions tab shortcut
    is always fixed to the latest year and must not be used).
    """
    step = make_step_logger(log, "AIS-FY", status_cb=status_cb)
    step(f"Navigating to AIS home tab to select F.Y. {fiscal_year}", portal,
         status=f"Selecting F.Y. {fiscal_year}…")

    try:
        ais_tab = portal.locator("nav.sub-navbar a").nth(1)
        step("Waiting for AIS sub-nav tab")
        await ais_tab.wait_for(state="visible", timeout=10000)
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
            await option.wait_for(state="visible", timeout=10000)
            await option.click()
            await asyncio.sleep(1)
            step(f"F.Y. {fiscal_year} selected — staying on AIS home tab")
        else:
            step(f"F.Y. {fiscal_year} already active — staying on AIS home tab")

    except Exception as e:
        step(f"Could not switch F.Y.: {e}")


async def _open_download_modal(portal: Page, log, label: str, status_cb=None) -> bool:
    """
    Click the download icon image in the relevant card on the AIS home tab
    to open the per-document download modal (mat-dialog-container).

    From the live DOM at /complianceportal/ais/home:
      TIS card footer:
        <img src="...download.svg"
             title="Download TIS related documents">
      AIS card footer (two icons — must target download, NOT upload):
        <img src="...upload.svg" title="Upload AIS feedback file ...">
        <img src="...download.svg" title="Download AIS related documents">

    The `title` attribute is unique per action and is the safest selector.
    Returns True if mat-dialog-container is visible after the click.
    """
    step = make_step_logger(log, f"{label}-MODAL", status_cb=status_cb)

    icon_titles = {
        "TIS": "Download TIS related documents",
        "AIS": "Download AIS related documents",
    }
    title = icon_titles.get(label, f"Download {label} related documents")

    # ── Primary: download icon image ──────────────────────────────────────────
    try:
        icon = portal.locator(f"img[title='{title}']").first
        step(f"Waiting for download icon: img[title='{title}']",
             status=f"Opening {label} download…")
        await icon.wait_for(state="visible", timeout=6000)
        step(f"Clicking {label} download icon")
        await icon.click(timeout=20000)
        await asyncio.sleep(1)
        modal = portal.locator("mat-dialog-container").first
        vis = await modal.is_visible(timeout=3000)
        step(f"Modal visible after icon click: {vis}")
        if vis:
            return True
    except Exception as e:
        step(f"Could not click {label} download icon: {e}")

    # ── Fallback: combined "Download AIS/TIS" button (Instructions page) ──────
    step("Trying combined 'Download AIS/TIS' button as fallback")
    try:
        btn = portal.locator("button:has-text('Download AIS/TIS')").first
        await btn.wait_for(state="visible", timeout=7000)
        step("Clicking 'Download AIS/TIS' button")
        await btn.click(timeout=20000)
        await asyncio.sleep(1)
        modal = portal.locator("mat-dialog-container").first
        vis = await modal.is_visible(timeout=3000)
        step(f"Modal visible after button click: {vis}")
        return bool(vis)
    except Exception as e:
        step(f"Could not open modal: {e}")
        return False


async def _open_tis_modal(portal: Page, log, status_cb=None) -> bool:
    return await _open_download_modal(portal, log, "TIS", status_cb=status_cb)


async def _open_ais_modal(portal: Page, log, status_cb=None) -> bool:
    return await _open_download_modal(portal, log, "AIS", status_cb=status_cb)


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
                       log, pan: str = "", dob: str = "", status_cb=None) -> bool:
    """
    Download TIS PDF. Always instant — no generation step needed.
    Opens TIS tile modal → clicks Download → saves file.
    """
    if status_cb:
        status_cb("⏳ Downloading TIS PDF…")
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
        opened = await _open_tis_modal(portal, log, status_cb=status_cb)
        if not opened:
            return _outcome("failed")
        modal = _modal_locator(portal)
        try:
            await modal.wait_for(state="visible", timeout=10000)
        except Exception:
            log("[TIS] Modal did not appear.")
            return _outcome("failed")

    await update_browser_status(portal, "AIS: Downloading TIS PDF...")
    dl = await _download_modal_row(
        portal,
        "Taxpayer Information Summary (TIS) - PDF",
        tis_file, log, "TIS", status_cb=status_cb)
    if dl.get("ok"):
        unlock = _unlock_and_warn(tis_file, pan=pan, dob=dob, log=log, label="TIS PDF", status_cb=status_cb)
        await _close_modal(portal, log)
        return _outcome("downloaded", unlocked=unlock.get("unlocked"), reason=unlock.get("reason"))
    await _close_modal(portal, log)
    dl_status = dl.get("status", "failed")
    return _outcome(dl_status if dl_status in ("no_data", "error") else "failed",
                    reason=dl.get("reason"))


# ── AIS Request ───────────────────────────────────────────────────────────────

async def request_ais(portal: Page, fiscal_year: str, download_dir: str,
                      log, pan: str = "", dob: str = "", status_cb=None) -> dict:
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

    opened = await _open_ais_modal(portal, log, status_cb=status_cb)
    if not opened:
        return {"status": "failed", "reason": "AIS download icon not found or modal did not open"}

    modal = _modal_locator(portal)
    try:
        await modal.wait_for(state="visible", timeout=10000)
    except Exception:
        log("[AIS] Modal did not appear.")
        return {"status": "failed", "reason": "AIS modal did not appear after click"}

    step = make_step_logger(log, "AIS-DL", status_cb=status_cb)
    try:
        # Target the PDF row specifically — the modal also contains JSON and ACF
        # download buttons; we must not accidentally click those.
        ais_pdf_row = modal.locator(
            "div, li, tr"
        ).filter(has_text="Annual Information Statement (AIS) - PDF").first
        dl_btn = ais_pdf_row.locator("button").first
        cnt = await modal.locator("button.dialog-outline-btn, button").count()
        step(f"Found {cnt} download button(s) in modal — targeting AIS-PDF row")
        await dl_btn.wait_for(state="visible", timeout=10000)
        step("AIS PDF Download button visible")
        await update_browser_status(portal, "AIS: Requesting AIS PDF...")

        # Wait for a download as a background task. Small file → it resolves with
        # a Download. Large file → no download ever fires; instead the modal shows
        # "Success ... Reference ID ..." + "Go To Activity History". We poll the
        # modal text in parallel and take whichever outcome arrives first, so the
        # large-file path returns promptly instead of waiting out the timeout.
        step("Clicking AIS PDF Download button", status="Downloading AIS PDF…")
        dl_task = asyncio.ensure_future(_wait_for_download(portal))
        await asyncio.sleep(0.2)  # let the download listener attach
        await dl_btn.click(timeout=20000)
        step("Click sent; detecting instant-download vs large-file-queued…")

        download = None
        queued_text = ""
        for _ in range(60):                       # up to ~30s safety window
            await asyncio.sleep(0.5)

            if dl_task.done():
                try:
                    download = dl_task.result()
                except Exception:
                    download = None
                break

            try:
                txt = await modal.inner_text()
            except Exception:
                txt = ""
            # Portal-side error: no AIS data for this FY.
            # Must be checked BEFORE the queued regex — "activity history" appears in
            # the portal's "no data" error page and would cause a false-positive queue detection.
            if _re.search(r"don't have any|do not have any", txt, _re.IGNORECASE):
                step(f"Portal: no AIS data for FY {fiscal_year}. Text: {txt[:200]!r}")
                log(f"[Warning] AIS: No AIS data available for FY {fiscal_year}.")
                if not dl_task.done():
                    dl_task.cancel()
                await _close_modal(portal, log)
                return _outcome("no_data", reason=f"No AIS data available for FY {fiscal_year}.")

            # Portal-side error: AIS data too large for PDF.
            # NOTE: "ais utility" is intentionally NOT included here — the modal always
            # contains "AIS Utility" as a normal download-option row, causing false positives.
            if _re.search(r"too large|unable to generate as pdf", txt, _re.IGNORECASE):
                step(f"Portal error: AIS data too large. Modal text: {txt[:300]!r}")
                log(f"[Warning] AIS PDF unavailable — portal says data is too large. "
                    f"Client must use the AIS Utility to view their AIS.")
                if not dl_task.done():
                    dl_task.cancel()
                await _close_modal(portal, log)
                return _outcome("too_large",
                               reason="AIS data is too large to generate as PDF. "
                                      "Client must download AIS JSON and use the AIS Utility app.")
            if _re.search(r"reference\s*id|activity history|submitted successfully|"
                          r"file is large", txt, _re.IGNORECASE):
                queued_text = txt
                step("Large-file success message detected")
                break

        # Path 1: instant download
        if download is not None:
            if not dl_task.done():
                dl_task.cancel()
            await download.save_as(ais_file)
            step(f"Download saved: {os.path.basename(ais_file)}")
            log(f"[Victory] AIS PDF downloaded: {os.path.basename(ais_file)}")
            unlock = _unlock_and_warn(ais_file, pan=pan, dob=dob, log=log, label="AIS PDF", status_cb=status_cb)
            await _close_modal(portal, log)
            return _outcome("downloaded", unlocked=unlock.get("unlocked"),
                            reason=unlock.get("reason"), file=ais_file)

        # Path 2: large file queued — capture Reference ID, stop waiting
        if not dl_task.done():
            dl_task.cancel()
        if not queued_text:
            try:
                queued_text = await modal.inner_text()
            except Exception:
                queued_text = ""
        ref_match = _re.search(r'Reference\s*(?:ID|No\.?)[:\s]*([A-Z0-9\-]+)',
                               queued_text, _re.IGNORECASE)
        ref_id = ref_match.group(1).strip() if ref_match else ""
        step(f"Large file — request queued. Reference ID: {ref_id or 'N/A'}")
        log(f"[AIS] AIS generation queued. Reference ID: {ref_id or 'N/A'}")
        await _close_modal(portal, log)
        return {"status": "requested", "ref_id": ref_id, "fy": fiscal_year}

    except Exception as e:
        log(f"[AIS] Request failed: {e}")
        await _close_modal(portal, log)
        # Build a short, human-readable reason (strip the internal class path)
        reason_str = str(e).split('\n')[0].strip()
        if len(reason_str) > 80:
            reason_str = reason_str[:77] + "..."
        return {"status": "failed", "reason": reason_str or "Unexpected error during AIS download"}


async def _download_modal_row(portal: Page, row_text: str, save_path: str,
                              log, label: str, status_cb=None) -> dict:
    """
    Click the Download button for `row_text` in the open modal and save the file.
    Returns {"ok": True} on success, or {"ok": False, "status": str, "reason": str}.
    status values: "no_data" | "error" | "timeout" | "failed"
    """
    import re as _re
    step = make_step_logger(log, f"{label}-DL", status_cb=status_cb)
    modal = _modal_locator(portal)
    try:
        row = modal.locator(
            f"div.d-flex:has(p.dialog-sub-head:has-text('{row_text}'))"
        ).first
        dl_btn = row.locator("button.dialog-outline-btn").first
        step(f"Waiting for '{row_text}' Download button")
        await dl_btn.wait_for(state="visible", timeout=10000)
        step("Clicking Download")
        async with portal.expect_download(timeout=60000) as dl_info:
            await dl_btn.click(timeout=20000)
            # Brief pause to let any inline portal error or "no data" banner render
            await asyncio.sleep(1.5)
            # Check for portal-side error shown inside the modal row
            try:
                err_el = row.locator("p.error, .error-msg, [class*='error'], mat-error").first
                if await err_el.is_visible(timeout=800):
                    err_text = (await err_el.inner_text()).strip()
                    if err_text:
                        raise RuntimeError(f"Portal error: {err_text}")
            except RuntimeError:
                raise
            except Exception:
                pass
            # Early "no data" check — avoids burning the full 60s download timeout
            try:
                modal_txt = (await modal.inner_text(timeout=2000)).strip()
                if _re.search(r"don't have any|do not have any", modal_txt, _re.IGNORECASE):
                    m = _re.search(r"((?:you )?(?:don't|do not) have any[^\n.!?]*[.!?]?)",
                                   modal_txt, _re.IGNORECASE)
                    reason = m.group(1).strip() if m else f"No {label} data for this FY"
                    raise RuntimeError(f"__no_data__: {reason}")
            except RuntimeError:
                raise
            except Exception:
                pass
        download = await dl_info.value
        await download.save_as(save_path)
        step(f"Saved: {os.path.basename(save_path)}")
        log(f"[Victory] {label} PDF downloaded: {os.path.basename(save_path)}")
        return {"ok": True}
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("__no_data__: "):
            reason = msg[len("__no_data__: "):]
            step(f"No data: {reason}")
            log(f"[Warning] {label}: {reason}")
            return {"ok": False, "status": "no_data", "reason": reason}
        step(f"Portal error: {e}")
        log(f"[Warning] {label}: {e}")
        return {"ok": False, "status": "error", "reason": str(e)}
    except Exception as e:
        # On timeout, check if the portal displayed a "no data" message instead
        if "timeout" in str(e).lower() or "Timeout" in type(e).__name__:
            try:
                modal_txt = (await modal.inner_text()).strip()
                if _re.search(r"don't have any|do not have any", modal_txt, _re.IGNORECASE):
                    m = _re.search(r"((?:you )?(?:don't|do not) have any[^\n.!?]*[.!?]?)",
                                   modal_txt, _re.IGNORECASE)
                    reason = m.group(1).strip() if m else f"No {label} data for this FY"
                    step(f"No data: {reason}")
                    log(f"[Warning] {label}: {reason}")
                    return {"ok": False, "status": "no_data", "reason": reason}
            except Exception:
                pass
        step(f"Download failed: {e}")
        return {"ok": False, "status": "failed", "reason": str(e)}


# ── AIS Download from Activity History ───────────────────────────────────────

async def download_ais_from_activity_history(portal: Page, fiscal_year: str,
                                              download_dir: str, log,
                                              pan: str = "", dob: str = "",
                                              ref_id: str = "",
                                              should_continue=None,
                                              status_cb=None) -> bool:
    """
    Navigate to Activity History and download the AIS PDF for the given FY.

    The row matches by Reference ID (preferred) or by the FY description
    ("AIS - F.Y. YYYY-YY"). A request shows a Progress icon while generating
    and a Download link once ready. We poll until ready, abortable via
    `should_continue` (a callable returning False to stop).
    """
    step = make_step_logger(log, "AIS-HIST", status_cb=status_cb)
    os.makedirs(download_dir, exist_ok=True)
    fy_str = fiscal_year.replace("-", "_")
    prefix = f"{pan}-" if pan else ""
    ais_file = os.path.join(download_dir, f"{prefix}AIS-{fy_str}.pdf")
    fy_desc = f"AIS - F.Y. {fiscal_year}"

    def _aborted():
        return should_continue is not None and not should_continue()

    step("Navigating to Activity History", portal, status="Opening Activity History…")
    await update_browser_status(portal, "AIS: Opening Activity History...")
    try:
        act_link = portal.locator("nav.ctm-navbar li.item a:has-text('Activity History')").first
        await act_link.wait_for(state="visible", timeout=20000)
        await act_link.click()
        await portal.wait_for_load_state("domcontentloaded", timeout=40000)
        await asyncio.sleep(2)
        step("Activity History loaded", portal)
    except Exception as e:
        step(f"Could not navigate to Activity History: {e}")
        return False

    # Try to maximise the page size so older-year rows are on the first page.
    try:
        sel = portal.locator("mat-paginator select, .mat-paginator-page-size select").first
        if await sel.is_visible(timeout=1500):
            opts = await sel.locator("option").all_inner_texts()
            if opts:
                largest = max(opts, key=lambda o: int(re.sub(r"\D", "", o) or 0))
                await sel.select_option(label=largest)
                step(f"Set Activity History page size to {largest.strip()}")
                await asyncio.sleep(1.5)
    except Exception:
        pass

    async def _dump_rows():
        try:
            rows = await portal.evaluate("""() => {
                const out = [];
                document.querySelectorAll('tr.example-element-row').forEach(tr => {
                    const act = tr.querySelector('td.mat-column-activityType');
                    const desc = tr.querySelector('td.mat-column-description');
                    const ref = tr.querySelector('td.mat-column-referenceId');
                    const dl = tr.querySelector('td.mat-column-download');
                    out.push({
                        activity: act ? act.innerText.trim() : '',
                        desc: desc ? desc.innerText.trim() : '',
                        ref: ref ? ref.innerText.trim() : '',
                        dlLink: !!(dl && dl.querySelector('a[title="Download file"]')),
                        progress: !!(dl && dl.querySelector('img[alt="Progress"]')),
                    });
                });
                return out;
            }""")
            step(f"Activity rows: {len(rows)}")
            for r in rows:
                if "AIS" in r["activity"]:
                    step(f"  row: act='{r['activity']}' desc='{r['desc']}' "
                         f"ref='{r['ref']}' dlLink={r['dlLink']} progress={r['progress']}")
        except Exception as de:
            step(f"Row dump failed: {de}")

    await _dump_rows()

    def _row_locator():
        # Match by Reference ID (best) or by FY description (any AIS activity row).
        if ref_id:
            return portal.locator(
                f"tr.example-element-row:has(td.mat-column-referenceId:has-text('{ref_id}'))"
            ).first
        return portal.locator(
            f"tr.example-element-row"
            f":has(td.mat-column-activityType:has-text('AIS'))"
            f":has(td.mat-column-description:has-text('{fy_desc}'))"
        ).first

    MAX_ATTEMPTS = 20
    POLL_INTERVAL = 30

    for attempt in range(MAX_ATTEMPTS):
        if _aborted():
            step("Aborted by user — stopping Activity History wait")
            return _outcome("aborted")

        if attempt > 0:
            step(f"Waiting for generation — attempt {attempt}/{MAX_ATTEMPTS-1}, {POLL_INTERVAL}s",
                 status=f"AIS generating on ITD servers… (check {attempt}/{MAX_ATTEMPTS-1})")
            await update_browser_status(
                portal, f"AIS: Waiting for generation ({attempt}/{MAX_ATTEMPTS-1})...")
            for _ in range(POLL_INTERVAL):
                if _aborted():
                    step("Aborted by user during wait")
                    return _outcome("aborted")
                await asyncio.sleep(1)
            try:
                await portal.reload(wait_until="domcontentloaded", timeout=40000)
                await asyncio.sleep(2)
            except Exception:
                pass

        try:
            row = _row_locator()
            cnt = await row.count()
            step(f"Matching AIS rows for '{fy_desc}': {cnt}")

            if cnt == 0:
                # No row at all on the FIRST check → the AIS was never requested
                # for this FY/client. Fail fast with a helpful message rather
                # than polling 10 minutes for something that will never appear.
                if attempt == 0:
                    step("No AIS request found for this FY — nothing to download")
                    log(f"[AIS] No AIS request found in Activity History for {fy_desc}.")
                    return _outcome("not_found")
                continue

            await row.wait_for(state="visible", timeout=10000)
            dl_cell = row.locator("td.mat-column-download").first

            try:
                dl_link = dl_cell.locator("a[title='Download file']").first
                is_ready = await dl_link.is_visible(timeout=500)
            except Exception:
                is_ready = False

            if is_ready:
                step("File ready — downloading", status="AIS ready — downloading…")
                await update_browser_status(portal, "AIS: Downloading from Activity History...")
                async with portal.expect_download(timeout=60000) as dl_info:
                    await dl_link.click()
                download = await dl_info.value
                await download.save_as(ais_file)
                step(f"Saved: {os.path.basename(ais_file)}")
                log(f"[Victory] AIS PDF saved: {os.path.basename(ais_file)}")
                unlock = _unlock_and_warn(ais_file, pan=pan, dob=dob, log=log, label="AIS PDF", status_cb=status_cb)
                return _outcome("downloaded", unlocked=unlock.get("unlocked"), reason=unlock.get("reason"))

            step(f"Row present, still generating (attempt {attempt+1})")

        except Exception as e:
            step(f"Row lookup error (attempt {attempt+1}): {e}")

    step("AIS generation timed out after ~10 minutes")
    log("[Warning] AIS generation timed out — try again later.")
    return _outcome("timeout")


# ── Top-level entry points (called from app.py) ───────────────────────────────

async def run_request_ais(itd_page: Page, fiscal_year: str, download_dir: str,
                          log, pan: str = "", dob: str = "",
                          status_callback=None) -> dict:
    """
    Phase 1 — Called from 'Request AIS' button.
    Opens portal, navigates to AIS tab, selects FY, requests AIS PDF generation.
    Returns result dict from request_ais().
    status_callback: optional callable(str) to update the Batch Progress UI.
    """
    def _status(msg):
        if status_callback:
            status_callback(msg)

    fy_start = int(fiscal_year.split("-")[0]) if "-" in fiscal_year else 0
    if fy_start < 2021:
        log(f"[AIS] Skipping — AIS not available before FY 2021-22.")
        return {"status": "skipped"}

    portal = None
    try:
        portal = await _open_ais_portal(itd_page, log, status_cb=status_callback)
        await _navigate_to_ais_tab(portal, log, status_cb=status_callback)
        await _select_fy(portal, fiscal_year, log, status_cb=status_callback)

        # AIS PDF (instant download or queued request)
        ais_outcome = await request_ais(portal, fiscal_year, download_dir, log,
                                        pan=pan, dob=dob, status_cb=status_callback)

        _status(_doc_label(ais_outcome, "AIS") + " — fetching TIS…")

        # TIS PDF — always instant, lives in its own modal.
        tis_outcome = _outcome("failed")
        try:
            tis_outcome = await download_tis(portal, fiscal_year, download_dir, log,
                                             pan=pan, dob=dob, status_cb=status_callback)
        except Exception as te:
            log(f"[TIS] TIS download error: {te}")

        # Final combined status
        _status(combined_status_label(ais_outcome, tis_outcome))

        await portal.close()
        # Keep backward-compat keys app.py uses, and add tis_outcome
        ais_outcome["tis"] = tis_outcome
        return ais_outcome
    except Exception as e:
        log(f"[AIS] Request phase failed: {e}")
        reason_str = str(e).split('\n')[0].strip()
        if len(reason_str) > 80:
            reason_str = reason_str[:77] + "..."
        if portal:
            try: await portal.close()
            except Exception: pass
        return _outcome("failed", reason=reason_str or "Unexpected error")



async def run_download_ais_tis(itd_page: Page, fiscal_year: str, download_dir: str,
                               log, pan: str = "", dob: str = "",
                               dl_ais: bool = True, dl_tis: bool = True,
                               ais_ref_id: str = "", should_continue=None,
                               status_callback=None) -> bool:
    """
    Phase 2 — Called from 'Download AIS/TIS' button.
    Downloads TIS instantly and AIS PDF from Activity History.
    """
    fy_start = int(fiscal_year.split("-")[0]) if "-" in fiscal_year else 0
    if fy_start < 2021:
        log(f"[AIS/TIS] Skipping — not available before FY 2021-22.")
        return {"ais": _outcome("skipped"), "tis": None}

    portal = None
    ais_outcome = None
    tis_outcome = None
    try:
        portal = await _open_ais_portal(itd_page, log, status_cb=status_callback)
        await _navigate_to_ais_tab(portal, log, status_cb=status_callback)
        await _select_fy(portal, fiscal_year, log, status_cb=status_callback)

        if dl_tis:
            tis_outcome = await download_tis(portal, fiscal_year, download_dir, log,
                                             pan=pan, dob=dob, status_cb=status_callback)
            if tis_outcome.get("status") != "downloaded":
                log("[Warning] TIS download failed.")

        if dl_ais:
            ais_outcome = await download_ais_from_activity_history(
                    portal, fiscal_year, download_dir, log,
                    pan=pan, dob=dob, ref_id=ais_ref_id,
                    should_continue=should_continue, status_cb=status_callback)

        # Emit final combined status
        if status_callback:
            status_callback(combined_status_label(ais_outcome, tis_outcome))

        await portal.close()
        return {"ais": ais_outcome, "tis": tis_outcome}
    except Exception as e:
        log(f"[AIS/TIS] Download phase failed: {e}")
        if portal:
            try: await portal.close()
            except Exception: pass
        return {"ais": ais_outcome or _outcome("failed"), "tis": tis_outcome}
