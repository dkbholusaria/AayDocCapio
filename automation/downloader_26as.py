import os, asyncio, zipfile, shutil
from playwright.async_api import Page, Frame
from automation.downloader import update_browser_status


async def _find_frame(page: Page, selector: str, timeout: int = 3000) -> Frame | None:
    """Return the first frame (including main) where selector is visible."""
    for frame in page.frames:
        try:
            await frame.locator(selector).first.wait_for(state="visible", timeout=timeout)
            return frame
        except Exception:
            continue
    return None


async def download_26as(page: Page, assessment_year: str, download_dir: str, log_callback, pan: str = "", dob: str = "") -> bool:
    try:
        log_callback("[26AS] Hovering over e-File menu...")
        efile = page.locator("//*[normalize-space(.)='e-File']").first
        await efile.wait_for(state="visible", timeout=15000)
        await efile.hover()
        await asyncio.sleep(1.0)
        log_callback("[26AS] Hovering over Income Tax Returns...")
        returns = page.locator("//*[text()='Income Tax Returns']").first
        await returns.wait_for(state="visible", timeout=15000)
        await returns.hover()
        await asyncio.sleep(1.0)
        log_callback("[26AS] Clicking View Form 26AS — waiting for TRACES to load...")
        await update_browser_status(page, "26AS: Opening TRACES portal...")
        view_26as = page.locator("//*[text()='View Form 26AS']").first
        await view_26as.wait_for(state="visible", timeout=15000)

        # TRACES may open in a new tab or navigate in the same tab
        try:
            async with page.context.expect_page(timeout=8000) as new_page_info:
                await view_26as.click()
            traces_page = await new_page_info.value
            await traces_page.wait_for_load_state("domcontentloaded", timeout=20000)
            log_callback("[26AS] TRACES opened in a new tab.")
        except Exception:
            traces_page = page
            await page.wait_for_load_state("domcontentloaded", timeout=20000)
            log_callback("[26AS] TRACES loaded in the same tab.")

        log_callback(f"[26AS] TRACES portal ready. Frames: {len(traces_page.frames)}")
        await update_browser_status(traces_page, "TRACES: Connected.")

        # Dismiss agreement popup — TRACES loads content in frames, so search all of them
        try:
            agree_frame = await _find_frame(traces_page, "input#Details, input[type='checkbox']", timeout=10000)
            if agree_frame:
                log_callback(f"[26AS] Agreement modal found in frame: {agree_frame.url[:60]}")
                await update_browser_status(traces_page, "TRACES: Accepting Terms & Conditions...")
                chk = agree_frame.locator("input#Details").first
                await chk.click()  # click (not check) so onclick JS fires and enables the Proceed button
                await asyncio.sleep(0.3)
                proceed_btn = agree_frame.locator("input#btn").first
                await proceed_btn.wait_for(state="visible", timeout=5000)
                await proceed_btn.click()
                log_callback("[26AS] Accepted TRACES agreement popup.")
                await traces_page.wait_for_load_state("domcontentloaded", timeout=15000)
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
        await traces_page.goto(view_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1.5)

        # Handle TDS defaults intermediate page (view26ASThrdPrty.xhtml) — appears when the PAN
        # has TDS defaults from branch TANs; must click "Proceed to View Annual Tax Statement"
        if "ThrdPrty" in traces_page.url or "view26ASThrdPrty" in traces_page.url:
            log_callback("[26AS] TDS defaults page detected — clicking Proceed to View Annual Tax Statement...")
            await update_browser_status(traces_page, "TRACES: Bypassing TDS defaults page...")
            proceed = traces_page.locator("input[value*='Proceed to View']").first
            await proceed.wait_for(state="visible", timeout=10000)
            await proceed.click()
            await traces_page.wait_for_load_state("domcontentloaded", timeout=20000)
            await asyncio.sleep(1.5)
            log_callback(f"[26AS] Proceeded — now on: {traces_page.url}")

        log_callback(f"[26AS] Selecting Assessment Year: {assessment_year}")
        await update_browser_status(traces_page, f"TRACES: Selecting AY {assessment_year}...")
        ay_frame = await _find_frame(traces_page, "select#AssessmentYearDropDown", timeout=15000)
        if not ay_frame:
            raise Exception("Could not find AssessmentYearDropDown on TRACES view26AS page.")
        await ay_frame.locator("select#AssessmentYearDropDown").first.select_option(label=assessment_year)
        # onchange fires updatePart() which enables btnSubmit — give JS a moment
        await asyncio.sleep(1)

        log_callback("[26AS] Selecting View As: HTML")
        await update_browser_status(traces_page, "TRACES: Selecting HTML format...")
        fmt_frame = await _find_frame(traces_page, "select#viewType", timeout=10000)
        if fmt_frame:
            await fmt_frame.locator("select#viewType").first.select_option(label="HTML")
            await asyncio.sleep(0.5)

        log_callback("[26AS] Clicking View / Download...")
        await update_browser_status(traces_page, "TRACES: Fetching Form data...")
        view_btn_frame = await _find_frame(traces_page, "input#btnSubmit", timeout=10000)
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

        ay_str = assessment_year.replace("-", "_")
        prefix = f"{pan}-" if pan else ""
        os.makedirs(download_dir, exist_ok=True)

        # ── PDF download ──────────────────────────────────────────────────────
        pdf_frame = await _find_frame(traces_page, "input#pdfBtn", timeout=5000)
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
        try:
            txt_fmt_frame = await _find_frame(traces_page, "select#viewType", timeout=5000)
            if txt_fmt_frame:
                await txt_fmt_frame.locator("select#viewType").first.select_option(label="Text")
                await asyncio.sleep(0.5)
            txt_btn_frame = await _find_frame(traces_page, "input#btnSubmit", timeout=5000)
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
        except Exception as txt_err:
            log_callback(f"[Warning] TXT download skipped: {txt_err}")

        await update_browser_status(traces_page, "TRACES: 26AS Download Complete!")
        await asyncio.sleep(1)
        await traces_page.close()
        return True
    except Exception as e:
        log_callback(f"[Error] Failed to download Form 26AS: {e}")
        return False
