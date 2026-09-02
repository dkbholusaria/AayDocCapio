import os, asyncio, zipfile, shutil, re
from playwright.async_api import Page, Frame
from automation.downloader import update_browser_status
from automation.diagnostics import capture_failure
from utils import migrate_flat_docs_to_subfolders


async def _find_frame(page: Page, selector: str, timeout: int = 3000) -> Frame | None:
    """Return the first frame (including main) where selector is visible."""
    for frame in page.frames:
        try:
            await frame.locator(selector).first.wait_for(state="visible", timeout=timeout)
            return frame
        except Exception:
            continue
    return None


async def _open_hamburger(page: Page, log_callback):
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
                log_callback(f"[26AS] Opening hamburger menu: {sel}")
                try:
                    await btn.click(timeout=3000)
                except Exception:
                    await btn.click(force=True, timeout=3000)
                await asyncio.sleep(1)
                return
        except Exception:
            continue


async def _click_efile_26as(page: Page, log_callback) -> None:
    """e-File is a stock Angular Material MatMenuTrigger, which opens on
    CLICK natively. A live diagnostics capture confirmed .hover() can
    "succeed" (mouse moved) without actually opening the menu when this
    runs as the second e-File-based handler in a batch — click is the
    always-on mechanism and doesn't depend on any custom hover glue script.
    See automation/_nav_helpers.py's matching function for the full
    writeup. Retry the full wait+click cycle — dashboard Angular nav may
    take time to mount even after the overlay clears."""
    for _attempt in range(4):
        try:
            efile = page.locator("//*[normalize-space(.)='e-File']").first
            await efile.wait_for(state="visible", timeout=30000)
            await efile.click(timeout=10000)
            return
        except Exception:
            if _attempt == 3:
                await capture_failure(page, log_callback, "26AS_efile_hover_failed")
                raise
            log_callback(f"[26AS] e-File menu not ready (attempt {_attempt + 1}/4) — waiting...")
            # Nudge the page to help Angular finish rendering the nav
            try:
                await page.keyboard.press("Escape")
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            await asyncio.sleep(5)


async def _navigate_to_traces_1_0(page: Page, log_callback) -> Page:
    """One-time navigation to TRACES 1.0's Tax Credit / view26AS.xhtml page —
    everything up to (but not including) selecting an Assessment Year, which
    is year-specific and belongs to the per-year step. F-14 (multi-year):
    this is the expensive/fragile part (e-File hover + a new-tab TRACES
    redirect), so it runs ONCE per client regardless of how many AY years
    are requested; callers loop `_download_26as_for_year()` afterward, which
    only reselects the AY dropdown on this already-open page per year."""
    await _open_hamburger(page, log_callback)

    # The ITD portal often leaves a full-screen loading spinner/overlay active
    # for a few seconds which intercepts pointer events. Wait for it to clear.
    try:
        await page.locator(".customLoaderBackdrop").wait_for(state="hidden", timeout=30000)
    except Exception:
        pass

    log_callback("[26AS] Opening e-File menu...")
    await _click_efile_26as(page, log_callback)
    await asyncio.sleep(1.0)
    log_callback("[26AS] Hovering over Income Tax Returns...")
    # See automation/_nav_helpers.py's hover_to_income_tax_returns() for
    # why this retries too (a live diagnostics capture on 2026-08-26
    # showed the e-File click landing correctly yet this step still
    # never appearing on a solo/first-ever run — this one step had no
    # retry at all, unlike the e-File click above).
    returns = page.locator("//*[text()='Income Tax Returns']").first
    for _attempt in range(4):
        try:
            await returns.wait_for(state="visible", timeout=15000)
            break
        except Exception:
            if _attempt == 3:
                await capture_failure(page, log_callback, "26AS_income_tax_returns_hover_failed")
                raise
            log_callback(f"[26AS] Income Tax Returns not ready (attempt {_attempt + 1}/4) — reopening e-File...")
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(1)
            except Exception:
                pass
            await _click_efile_26as(page, log_callback)
            await asyncio.sleep(1.0)
    await returns.hover()
    await asyncio.sleep(1.0)
    log_callback("[26AS] Clicking View Form 26AS — waiting for TRACES to load...")
    await update_browser_status(page, "26AS: Opening TRACES portal...")
    view_26as = page.locator("//*[contains(text(),'View Form 26AS')]").first
    await view_26as.wait_for(state="visible", timeout=30000)

    # TRACES may open in a new tab or navigate in the same tab
    try:
        async with page.context.expect_page(timeout=40000) as new_page_info:
            await view_26as.click()

            # The ITD portal sometimes shows a "Disclaimer" popup asking to confirm
            # the redirect to TRACES. We MUST click "Confirm" if it appears, otherwise
            # the new tab will never spawn and expect_page will time out.
            try:
                confirm_btn = page.locator("button", has_text=re.compile(r"confirm|proceed", re.IGNORECASE)).first
                await confirm_btn.wait_for(state="visible", timeout=4000)
                await confirm_btn.click()
                log_callback("[26AS] Confirmed TRACES redirect popup on ITD portal.")
            except Exception:
                # No confirm popup appeared, which is fine
                pass

        traces_page = await new_page_info.value
        await traces_page.wait_for_load_state("domcontentloaded", timeout=40000)
        log_callback("[26AS] TRACES opened in a new tab.")
    except Exception:
        traces_page = page
        await page.wait_for_load_state("domcontentloaded", timeout=40000)
        log_callback("[26AS] TRACES loaded in the same tab.")

    log_callback(f"[26AS] TRACES portal ready. Frames: {len(traces_page.frames)}")
    await update_browser_status(traces_page, "TRACES: Connected.")

    # Dismiss agreement popup — TRACES loads content in frames, so search all of them
    try:
        agree_frame = await _find_frame(traces_page, "input#Details, input[type='checkbox']", timeout=20000)
        if agree_frame:
            log_callback(f"[26AS] Agreement modal found in frame: {agree_frame.url[:60]}")
            await update_browser_status(traces_page, "TRACES: Accepting Terms & Conditions...")
            chk = agree_frame.locator("input#Details").first
            await chk.click()  # click (not check) so onclick JS fires and enables the Proceed button
            await asyncio.sleep(0.3)
            proceed_btn = agree_frame.locator("input#btn").first
            await proceed_btn.wait_for(state="visible", timeout=10000)
            await proceed_btn.click()
            log_callback("[26AS] Accepted TRACES agreement popup.")
            await traces_page.wait_for_load_state("domcontentloaded", timeout=30000)
            await asyncio.sleep(1.5)
        else:
            log_callback("[26AS] No agreement popup found — continuing.")
    except Exception as err:
        log_callback(f"[26AS] Warning: Agreement popup issue ({err}). Continuing...")

    log_callback("[26AS] Navigating to Tax Credit section...")
    await update_browser_status(traces_page, "TRACES: Loading Tax Credit Section...")
    base_url = traces_page.url.rsplit('/serv/', 1)[0]
    view_url = f"{base_url}/serv/tapn/view26AS.xhtml"
    log_callback(f"[26AS] Going to: {view_url}")
    await traces_page.goto(view_url, wait_until="domcontentloaded", timeout=40000)
    await asyncio.sleep(1.5)

    # Handle TDS defaults intermediate page (view26ASThrdPrty.xhtml) — appears when the PAN
    # has TDS defaults from branch TANs; must click "Proceed to View Annual Tax Statement"
    if "ThrdPrty" in traces_page.url or "view26ASThrdPrty" in traces_page.url:
        log_callback("[26AS] TDS defaults page detected — clicking Proceed to View Annual Tax Statement...")
        await update_browser_status(traces_page, "TRACES: Bypassing TDS defaults page...")
        proceed = traces_page.locator("input[value*='Proceed to View']").first
        await proceed.wait_for(state="visible", timeout=20000)
        await proceed.click()
        await traces_page.wait_for_load_state("domcontentloaded", timeout=40000)
        await asyncio.sleep(1.5)
        log_callback(f"[26AS] Proceeded — now on: {traces_page.url}")

    return traces_page


async def _download_26as_for_year(traces_page: Page, assessment_year: str, download_dir: str,
                                   log_callback, pan: str = "", dob: str = "") -> tuple[bool, str, str]:
    """Downloads Form 26AS PDF+TXT for ONE Assessment Year, assuming
    `_navigate_to_traces_1_0()` has already landed on the TRACES view26AS
    page. Does NOT close `traces_page` — the caller reuses it across years
    and closes it once at the end."""
    try:
        log_callback(f"[26AS] Selecting Assessment Year: {assessment_year}")
        await update_browser_status(traces_page, f"TRACES: Selecting AY {assessment_year}...")
        ay_frame = await _find_frame(traces_page, "select#AssessmentYearDropDown", timeout=30000)
        if not ay_frame:
            raise Exception("Could not find AssessmentYearDropDown on TRACES view26AS page.")
        for _ay_attempt in range(3):
            try:
                await ay_frame.locator("select#AssessmentYearDropDown").first.select_option(
                    label=assessment_year, timeout=10000)
                break
            except Exception:
                if _ay_attempt == 2:
                    raise
                log_callback(f"[26AS] AY selection failed, retrying ({_ay_attempt + 1}/3)...")
                await asyncio.sleep(2)
        # onchange fires updatePart() which enables btnSubmit — give JS a moment
        await asyncio.sleep(1)

        log_callback("[26AS] Selecting View As: HTML")
        await update_browser_status(traces_page, "TRACES: Selecting HTML format...")
        fmt_frame = await _find_frame(traces_page, "select#viewType", timeout=20000)
        if fmt_frame:
            await fmt_frame.locator("select#viewType").first.select_option(label="HTML")
            await asyncio.sleep(0.5)

        log_callback("[26AS] Clicking View / Download...")
        await update_browser_status(traces_page, "TRACES: Fetching Form data...")
        view_btn_frame = await _find_frame(traces_page, "input#btnSubmit", timeout=20000)
        if not view_btn_frame:
            raise Exception("Could not find btnSubmit on TRACES view26AS page.")
        await view_btn_frame.locator("input#btnSubmit").first.click()

        log_callback("[26AS] Waiting for 26AS data to load...")
        await update_browser_status(traces_page, "TRACES: Loading 26AS data...")
        # The loading div is shown during AJAX fetch — wait for it to appear then disappear
        loading = traces_page.locator("#loading")
        try:
            await loading.wait_for(state="visible", timeout=8000)
            await loading.wait_for(state="hidden", timeout=60000)
        except Exception:
            await asyncio.sleep(5)  # fallback if loading div not detected

        # ── Large-file on-demand check ────────────────────────────────────────
        # TRACES shows div#message when the 26AS is too large to serve inline.
        # In that case pdfBtn/btnSubmit are absent — detect early and fail cleanly.
        # Does NOT close traces_page — a different year for the same client may
        # still be fine, and the caller closes the tab once at the end.
        for frame in traces_page.frames:
            try:
                msg_el = frame.locator("div#message")
                if await msg_el.count() > 0:
                    msg_text = (await msg_el.first.inner_text()).strip()
                    if msg_text:
                        log_callback(f"[Warning] TRACES on-demand message: {msg_text[:120]}")
                        return False, (
                            "26AS too large for inline download — login to tdscpc.gov.in "
                            "to place a download request, then download the TXT manually."
                        ), ""
            except Exception:
                continue

        ay_str = assessment_year.replace("-", "_")
        prefix = f"{pan}-" if pan else ""
        migrate_flat_docs_to_subfolders(download_dir, log_callback)
        download_dir = os.path.join(download_dir, "26AS")
        os.makedirs(download_dir, exist_ok=True)

        # ── PDF download ──────────────────────────────────────────────────────
        pdf_frame = await _find_frame(traces_page, "input#pdfBtn", timeout=10000)
        if not pdf_frame:
            raise Exception("Could not find pdfBtn on TRACES view26AS page.")
        pdf_btn = pdf_frame.locator("input#pdfBtn").first

        log_callback("[26AS] Exporting Form 26AS to PDF...")
        await update_browser_status(traces_page, "TRACES: Downloading PDF file...")
        output_pdf = os.path.join(download_dir, f"{prefix}26AS-{ay_str}.pdf")
        async with traces_page.expect_download() as download_info:
            await pdf_btn.click()
        await (await download_info.value).save_as(output_pdf)
        log_callback(f"[Victory] Form 26AS PDF downloaded: {os.path.basename(output_pdf)}")

        # ── TXT download ──────────────────────────────────────────────────────
        # Switch View As to "Text" and re-submit — TRACES streams the .txt directly
        log_callback("[26AS] Switching to Text format for TXT download...")
        await update_browser_status(traces_page, "TRACES: Downloading TXT file...")
        _saved_txt = ""
        try:
            txt_fmt_frame = await _find_frame(traces_page, "select#viewType", timeout=10000)
            if txt_fmt_frame:
                await txt_fmt_frame.locator("select#viewType").first.select_option(label="Text")
                await asyncio.sleep(0.5)
            txt_btn_frame = await _find_frame(traces_page, "input#btnSubmit", timeout=10000)
            if not txt_btn_frame:
                raise Exception("btnSubmit not found for TXT download")
            output_txt = os.path.join(download_dir, f"{prefix}26AS-{ay_str}.txt")
            tmp_path = output_txt + ".download"
            async with traces_page.expect_download(timeout=30000) as txt_dl_info:
                await txt_btn_frame.locator("input#btnSubmit").first.click()
            await (await txt_dl_info.value).save_as(tmp_path)

            # TRACES wraps the .txt inside a password-protected ZIP
            # Password is DOB in ddmmyyyy format (e.g. 01-01-1980 → 11101980)
            if zipfile.is_zipfile(tmp_path):
                zip_pwd = dob.replace("-", "").encode() if dob else None
                pwd_display = zip_pwd.decode() if zip_pwd else "(no DOB)"
                log_callback(f"[26AS] Unlocking ZIP with password: {pwd_display}")
                with zipfile.ZipFile(tmp_path, "r") as zf:
                    names = zf.namelist()
                    txt_name = next((n for n in names if n.lower().endswith(".txt")), names[0])
                    extracted = zf.extract(txt_name, download_dir, pwd=zip_pwd)
                os.replace(extracted, output_txt)
                os.remove(tmp_path)
                log_callback(f"[Victory] Form 26AS TXT extracted from ZIP: {os.path.basename(output_txt)}")
            else:
                os.replace(tmp_path, output_txt)
                log_callback(f"[Victory] Form 26AS TXT downloaded: {os.path.basename(output_txt)}")
            _saved_txt = output_txt
        except Exception as txt_err:
            # Rename the leftover .download temp file to .zip so the user can
            # open it manually with the correct password.
            zip_hint = ""
            try:
                zip_path = output_txt.rsplit(".", 1)[0] + ".zip"
                if os.path.exists(tmp_path):
                    os.replace(tmp_path, zip_path)
                    zip_hint = f" Encrypted ZIP saved as: {os.path.basename(zip_path)}"
            except Exception:
                pass
            _txt_warning = str(txt_err)
            if "bad password" in _txt_warning.lower():
                pwd_display = dob.replace("-", "") if dob else "(no DOB)"
                log_callback(
                    f"[Warning] TXT ZIP unlock failed — wrong password (tried: {pwd_display}). "
                    f"Verify DOB in vault matches PAN card (format: DDMMYYYY).{zip_hint}"
                )
            else:
                log_callback(f"[Warning] TXT download failed: {_txt_warning}{zip_hint}")

        await update_browser_status(traces_page, "TRACES: 26AS Download Complete!")
        await asyncio.sleep(1)
        # _saved_txt is empty if TXT extraction failed
        txt_warn = "" if _saved_txt else "PDF saved but TXT extraction failed — check DOB in vault"
        return True, txt_warn, _saved_txt
    except Exception as e:
        err = str(e)
        log_callback(f"[Error] Failed to download Form 26AS for AY {assessment_year}: {err}")
        # Produce a short, human-readable reason for the status column
        if "Timeout" in err or "timeout" in err:
            if "e-File" in err or "normalize-space" in err:
                reason = "Timed out — ITD dashboard still loading (try again)"
            else:
                reason = "Timed out waiting for portal response (try again)"
        elif "net::" in err.lower():
            reason = "Network error — check internet connection"
        elif "Target page" in err or "browser has been closed" in err:
            reason = "Browser closed unexpectedly"
        else:
            reason = err[:80] if len(err) <= 80 else err[:77] + "..."
        return False, reason, ""


async def download_26as(page: Page, assessment_years: list[str], download_dir_for_year,
                         log_callback, pan: str = "", dob: str = "",
                         on_year_start=None) -> dict[str, tuple[bool, str, str]]:
    """F-14 (multi-year) entry point. Navigates to TRACES 1.0's Tax Credit
    section ONCE, then for each Assessment Year in `assessment_years`:
    reselects the AY dropdown on the same already-open TRACES tab and
    downloads that year's PDF+TXT into `download_dir_for_year(assessment_year)`.
    Returns {assessment_year: (ok, msg, txt_path)} — same per-year result
    shape the single-year version used to return directly.

    `on_year_start(assessment_year)`, if given, fires right before that
    year's download begins."""
    results: dict[str, tuple[bool, str, str]] = {}
    try:
        traces_page = await _navigate_to_traces_1_0(page, log_callback)
    except Exception as e:
        err = str(e)
        log_callback(f"[Error] Failed to reach TRACES for Form 26AS: {err}")
        if "Timeout" in err or "timeout" in err:
            reason = "Timed out — ITD dashboard still loading (try again)"
        else:
            reason = err[:80] if len(err) <= 80 else err[:77] + "..."
        for ay in assessment_years:
            results[ay] = (False, reason, "")
        return results

    try:
        for assessment_year in assessment_years:
            if on_year_start:
                on_year_start(assessment_year)
            download_dir = download_dir_for_year(assessment_year)
            results[assessment_year] = await _download_26as_for_year(
                traces_page, assessment_year, download_dir, log_callback, pan=pan, dob=dob)
    finally:
        try:
            await traces_page.close()
        except Exception:
            pass
    return results
