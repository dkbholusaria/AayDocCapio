import os
import asyncio
from playwright.async_api import Page, Download


def make_step_logger(log_callback, prefix: str, status_cb=None):
    """
    Returns a `step(msg, page=None, status=None)` function that:
      - always writes a granular, numbered log line (for diagnosis), and
      - optionally pushes a short, user-friendly `status` to the batch-progress
        row via `status_cb` (so the user sees what's happening in the BG).

        step = make_step_logger(log, "AIS", status_cb=set_status_for_this_pan)
        step("Clicking a#AIS", page, status="Opening AIS portal…")
        -> log:    [AIS] (3) Clicking a#AIS  |  url: https://...
        -> status: ⏳ Opening AIS portal…
    """
    counter = {"n": 0}

    def step(msg: str, page: Page = None, status: str = None):
        counter["n"] += 1
        line = f"[{prefix}] ({counter['n']}) {msg}"
        if page is not None:
            try:
                line += f"  |  url: {page.url}"
            except Exception:
                pass
        log_callback(line)
        if status and status_cb:
            try:
                status_cb(f"⏳ {status}" if not status[:1].strip().startswith(
                    ("✅", "❌", "🕐", "⬜", "⏹", "⏳")) else status)
            except Exception:
                pass

    return step


async def update_browser_status(page: Page, text: str):
    """
    Injects or updates a floating badge at the top of the browser page to display the current automation step.
    Uses pointer-events: none to prevent click interference.
    Runs persistently inside an interval and injects into child frames (necessary for TRACES/TDSCPC).
    """
    try:
        js_code = f"""
        (function() {{
            const textVal = {repr(text.upper())};
            window._statusText = textVal;
            
            function injectBadge(doc, txt) {{
                if (!doc) return;
                let badge = doc.getElementById('automation-status-badge');
                if (!badge) {{
                    badge = doc.createElement('div');
                    badge.id = 'automation-status-badge';
                    badge.style.position = 'fixed';
                    badge.style.top = '12px';
                    badge.style.left = '50%';
                    badge.style.transform = 'translateX(-50%)';
                    badge.style.backgroundColor = 'rgba(15, 23, 42, 0.95)';
                    badge.style.color = '#38bdf8';
                    badge.style.padding = '8px 18px';
                    badge.style.borderRadius = '24px';
                    badge.style.fontFamily = 'system-ui, -apple-system, sans-serif';
                    badge.style.fontSize = '12px';
                    badge.style.fontWeight = 'bold';
                    badge.style.zIndex = '2147483647';
                    badge.style.boxShadow = '0 8px 24px rgba(0, 0, 0, 0.25)';
                    badge.style.border = '1px solid #0284c7';
                    badge.style.pointerEvents = 'none';
                    badge.style.transition = 'all 0.3s ease';
                    badge.style.letterSpacing = '0.5px';
                    badge.style.whiteSpace = 'nowrap';
                    const parent = doc.body || doc.documentElement;
                    if (parent) {{
                        parent.appendChild(badge);
                    }}
                }}
                badge.innerText = txt;
            }}
            
            if (!window._statusInterval) {{
                window._statusInterval = setInterval(() => {{
                    const currentText = window._statusText || "";
                    injectBadge(document, currentText);
                    try {{
                        const frames = document.querySelectorAll('frame, iframe');
                        for (let i = 0; i < frames.length; i++) {{
                            try {{
                                const frameDoc = frames[i].contentDocument || frames[i].contentWindow.document;
                                injectBadge(frameDoc, currentText);
                            }} catch(fe) {{}}
                        }}
                    }} catch(e) {{}}
                }}, 500);
            }}
            
            injectBadge(document, textVal);
        }})();
        """
        await page.evaluate(js_code)
    except Exception:
        pass

async def click_xpath(page: Page, xpath_selector: str, log_callback):
    """
    Executes a zero-scroll mouse-over and click via JavaScript.
    Adapted from the KarOrbis engine-level zero-scroll click strategy.
    Broadens selectors to be tag-agnostic (e.g. converting //a[ or //span[ to //*[).
    """
    try:
        # Broaden selector to be tag-agnostic (essential for responsive/hybrid layouts)
        safe_selector = xpath_selector.replace("//a[", "//*[").replace("//span[", "//*[")
        element = page.locator(safe_selector).first
        await element.wait_for(state="visible", timeout=15000)
        
        # Real Playwright Hover & Click to trigger native event listeners (Angular/React)
        try:
            await element.hover(timeout=5000)
            await asyncio.sleep(0.5)
            await element.click(force=True, scroll_into_view_if_needed=False, timeout=5000)
            await asyncio.sleep(1.5)
        except Exception:
            # Fallback to zero-scroll JS pulse if native interaction is blocked
            try:
                await page.evaluate(
                    "(sel) => { const el = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; if(el) { const ev = new MouseEvent('mouseover', {bubbles: true}); el.dispatchEvent(ev); } }",
                    safe_selector
                )
                await asyncio.sleep(0.5)
                
                await page.evaluate(
                    "(sel) => { const el = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; if(el) el.click(); }",
                    safe_selector
                )
                await asyncio.sleep(1.5)
            except Exception as js_err:
                log_callback(f"[Warning] Both native click and JS click failed for '{xpath_selector}': {js_err}")
                raise js_err
    except Exception as e:
        log_callback(f"[Warning] Failed to select element '{xpath_selector}': {e}")
        raise e

async def download_26as(page: Page, assessment_year: str, download_dir: str, log_callback) -> bool:
    """
    Automates Form 26AS download from TRACES.
    """
    try:
        log_callback("[26AS] Initiating navigation to Form 26AS...")
        await update_browser_status(page, "26AS: Navigating to View Form 26AS...")
        
        # Navigation path to e-File > Income Tax Returns > View Form 26AS
        # 1. Hover over e-File menu
        log_callback("[26AS] Hovering over e-File menu...")
        efile = page.locator("//*[normalize-space(.)='e-File']").first
        await efile.wait_for(state="visible", timeout=15000)
        await efile.hover()
        await asyncio.sleep(1.0)
        
        # 2. Hover over Income Tax Returns submenu
        log_callback("[26AS] Hovering over Income Tax Returns...")
        returns = page.locator("//*[text()='Income Tax Returns']").first
        await returns.wait_for(state="visible", timeout=15000)
        await returns.hover()
        await asyncio.sleep(1.0)
        
        # 3. Click View Form 26AS
        log_callback("[26AS] Clicking View Form 26AS...")
        view_26as = page.locator("//*[text()='View Form 26AS']").first
        await view_26as.wait_for(state="visible", timeout=15000)
        await view_26as.click()
        await asyncio.sleep(2.0)
        
        log_callback("[26AS] Waiting for redirection warning dialog...")
        await update_browser_status(page, "26AS: Waiting for redirection warning...")
        confirm_btn = page.locator(
            "//button[normalize-space(.)='Confirm'] | //button[contains(text(), 'Confirm')] | "
            "//a[normalize-space(.)='Confirm'] | //a[contains(text(), 'Confirm')] | "
            "//input[@value='Confirm']"
        ).first
        await confirm_btn.wait_for(state="visible", timeout=15000)
        
        log_callback("[26AS] Clicking Confirm to redirect to TRACES...")
        await update_browser_status(page, "26AS: Redirecting to TRACES portal...")
        # Clicking confirm opens TRACES in a new tab
        async with page.context.expect_page() as new_page_info:
            await confirm_btn.click()
        
        traces_page = await new_page_info.value
        await traces_page.wait_for_load_state("domcontentloaded")
        log_callback("[26AS] Redirected to TRACES portal.")
        await update_browser_status(traces_page, "TRACES: Connected.")
        
        # Dismiss agreement popup if it appears
        try:
            # Target the checkbox and label specifically inside the active #imageModel dialog container
            agree_chk = traces_page.locator("//*[@id='imageModel']//input[@id='Details'] | //input[@id='Details']").first
            agree_label = traces_page.locator("//*[@id='imageModel']//*[contains(text(), 'I agree') or contains(text(), 'usage and acceptance')]").first
            
            # Wait for either of them to become visible
            try:
                await agree_chk.wait_for(state="visible", timeout=10000)
            except Exception:
                await agree_label.wait_for(state="visible", timeout=10000)
                
            await update_browser_status(traces_page, "TRACES: Accepting Terms & Conditions...")
            
            # Try checking the checkbox first
            try:
                await agree_chk.check(force=True, timeout=5000)
            except Exception:
                # If that fails, click the label/text next to it (toggles standard checkboxes)
                await agree_label.click(force=True, timeout=5000)
                
            await asyncio.sleep(1.0)
            
            # Target the Proceed button inside the active #imageModel dialog container
            proceed_btn = traces_page.locator("//*[@id='imageModel']//input[@value='Proceed' or @id='btn'] | //input[@value='Proceed' or @id='btn']").first
            await proceed_btn.click()
            log_callback("[26AS] Accepted TRACES agreement popup.")
            await asyncio.sleep(2)
        except Exception as err:
            log_callback(f"[26AS] Info: Agreement popup dismiss issue ({err}). Proceeding...")
 
        # Click "View Tax Credit (Form 26AS)"
        log_callback("[26AS] Navigating to Tax Credit section...")
        await update_browser_status(traces_page, "TRACES: Loading Tax Credit Section...")
        view_26as_link = traces_page.locator("p.paraFont a, //p[contains(@class, 'paraFont')]//a, //a[contains(@href, 'view26AS')]").first
        await view_26as_link.wait_for(state="visible", timeout=15000)
        await view_26as_link.click()
        await asyncio.sleep(2)
 
        # Select Assessment Year
        log_callback(f"[26AS] Selecting Assessment Year: {assessment_year}")
        await update_browser_status(traces_page, f"TRACES: Selecting AY {assessment_year}...")
        ay_select = traces_page.locator("select#ddlAY, select[name*='AY']").first
        await ay_select.wait_for(state="visible", timeout=15000)
        await ay_select.select_option(label=assessment_year)
        await asyncio.sleep(1)
 
        # Select Format: HTML
        log_callback("[26AS] Selecting Format: HTML")
        await update_browser_status(traces_page, "TRACES: Selecting Format (HTML)...")
        format_select = traces_page.locator("select#ddlHTML, select[name*='HTML'], select[name*='Format']").first
        await format_select.select_option(label="HTML")
        await asyncio.sleep(1)
 
        # Click View / Download button
        log_callback("[26AS] Fetching Form 26AS details...")
        await update_browser_status(traces_page, "TRACES: Fetching Form data...")
        view_btn = traces_page.locator("input#btnview, input[value='View / Download'], button:has-text('View')").first
        await view_btn.click()
        
        # Wait for the document to render and the "Export as PDF" button to be visible
        pdf_btn = traces_page.locator("input#btnPdf, input[value='Export as PDF'], #btnPdf").first
        await pdf_btn.wait_for(state="visible", timeout=25000)
        
        log_callback("[26AS] Exporting Form 26AS to PDF...")
        await update_browser_status(traces_page, "TRACES: Downloading PDF File...")
        # Capture and save file download
        async with traces_page.expect_download() as download_info:
            await pdf_btn.click()
        
        download = await download_info.value
        
        # Save output
        output_file = os.path.join(download_dir, f"Form_26AS_AY_{assessment_year.replace('-', '_')}.pdf")
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        await download.save_as(output_file)
        
        log_callback(f"[Victory] Form 26AS downloaded successfully: {os.path.basename(output_file)}")
        await update_browser_status(traces_page, "TRACES: 26AS Download Complete!")
        await asyncio.sleep(1)
        
        # Close the TRACES tab
        await traces_page.close()
        return True
        
    except Exception as e:
        log_callback(f"[Error] Failed to download Form 26AS: {e}")
        return False

async def download_ais_tis(page: Page, assessment_year: str, download_dir: str, log_callback) -> bool:
    """
    Automates AIS (Annual Information Statement) and TIS (Taxpayer Information Summary) download.
    """
    try:
        log_callback("[AIS/TIS] Initiating navigation to AIS Portal...")
        await update_browser_status(page, "AIS/TIS: Opening AIS Portal...")
        
        # Click AIS in top navigation (direct link)
        log_callback("[AIS/TIS] Clicking AIS top menu link...")
        ais = page.locator("//*[normalize-space(.)='AIS']").first
        await ais.wait_for(state="visible", timeout=15000)
        await ais.click()
        await asyncio.sleep(2.0)
        
        log_callback("[AIS/TIS] Waiting for compliance redirection popup...")
        await update_browser_status(page, "AIS/TIS: Redirection alert detected...")
        proceed_btn = page.locator(
            "//button[normalize-space(.)='Proceed'] | //button[contains(text(), 'Proceed')] | "
            "//a[normalize-space(.)='Proceed'] | //a[contains(text(), 'Proceed')] | "
            "//input[@value='Proceed']"
        ).first
        await proceed_btn.wait_for(state="visible", timeout=15000)
        
        log_callback("[AIS/TIS] Clicking Proceed to redirect to Compliance Portal...")
        await update_browser_status(page, "AIS/TIS: Opening Compliance Portal...")
        async with page.context.expect_page() as new_page_info:
            await proceed_btn.click()
            
        compliance_page = await new_page_info.value
        await compliance_page.wait_for_load_state("domcontentloaded")
        log_callback("[AIS/TIS] Redirected to Compliance Portal.")
        await update_browser_status(compliance_page, "Compliance: Loading Dashboard...")
        
        # Dismiss instructions or tour popups
        try:
            close_tour = compliance_page.locator("//button[text()='OK' or text()='Ok' or text()='Close' or text()='Dismiss' or text()='Skip'] | //a[text()='Close' or text()='Skip']").first
            if await close_tour.is_visible(timeout=5000):
                await update_browser_status(compliance_page, "Compliance: Dismissing tour overlays...")
                await close_tour.click()
                log_callback("[AIS/TIS] Dismissed introduction alert.")
                await asyncio.sleep(1)
        except Exception:
            pass
 
        # Click the "AIS" tile/card
        log_callback("[AIS/TIS] Loading AIS & TIS section...")
        await update_browser_status(compliance_page, "Compliance: Opening AIS Details...")
        ais_tile = compliance_page.locator("//div[contains(text(), 'Annual Information Statement') or contains(text(), 'AIS')] | //h6[text()='AIS'] | //a[contains(., 'AIS') or contains(., 'Annual Information Statement')]").first
        await ais_tile.wait_for(state="visible", timeout=20000)
        await ais_tile.click()
        await asyncio.sleep(3)
 
        # Select Assessment Year
        log_callback(f"[AIS/TIS] Selecting Assessment Year: {assessment_year}")
        await update_browser_status(compliance_page, f"Compliance: Selecting AY {assessment_year}...")
        try:
            select_el = compliance_page.locator("select[name*='AY'], select[id*='AY'], select.form-control").first
            if await select_el.is_visible(timeout=3000):
                await select_el.select_option(label=assessment_year)
            else:
                dropdown_trigger = compliance_page.locator("//mat-select | //div[contains(@class, 'select')] | //button[contains(@class, 'dropdown')] | //div[contains(text(), '2024-25') or contains(text(), '2023-24')]").first
                await dropdown_trigger.click()
                await asyncio.sleep(1)
                option = compliance_page.locator(f"//mat-option//span[contains(text(), '{assessment_year}')] | //div[contains(@class, 'option') and contains(text(), '{assessment_year}')] | //li[contains(text(), '{assessment_year}')]").first
                await option.click()
            await asyncio.sleep(2.5)
            log_callback(f"[AIS/TIS] Year successfully selected: {assessment_year}")
        except Exception as e:
            log_callback(f"[AIS/TIS] Info: Using active/default year on portal ({e}).")
 
        # Locate download buttons for TIS and AIS
        # In the modern ITD compliance portal, there are two distinct panels or tabs: 
        # one for Taxpayer Information Summary (TIS) and one for Annual Information Statement (AIS)
        
        # 1. TIS Download (PDF)
        log_callback("[TIS] Preparing download for Taxpayer Information Summary...")
        await update_browser_status(compliance_page, "Compliance: Downloading TIS PDF...")
        try:
            # We click download in the TIS section
            # The selector usually corresponds to the download icon inside the TIS card or row
            tis_download_btn = compliance_page.locator("//div[contains(@class, 'tis') or contains(text(), 'Taxpayer Information Summary') or contains(text(), 'TIS')]//following::button[contains(., 'Download') or @title='Download'] | //button[contains(@id, 'tis') or contains(@class, 'tis') and contains(@class, 'download')]").first
            if not await tis_download_btn.is_visible(timeout=5000):
                # Fallback to general download icons
                tis_download_btn = compliance_page.locator("//button[contains(., 'Download') or @title='Download']").nth(0)
                
            await tis_download_btn.click()
            await asyncio.sleep(1.5)
            
            # Select format (PDF is typically option 1/default, or select button with text PDF)
            pdf_select = compliance_page.locator("//button[contains(., 'PDF') or contains(text(), 'PDF')] | //a[contains(., 'PDF')]").first
            
            async with compliance_page.expect_download() as download_info:
                if await pdf_select.is_visible(timeout=3000):
                    await pdf_select.click()
                else:
                    # Click first download button in the modal
                    await compliance_page.locator(".modal-body button, .dialog button, button:has-text('Download')").first.click()
            
            download = await download_info.value
            tis_file = os.path.join(download_dir, f"TIS_AY_{assessment_year.replace('-', '_')}.pdf")
            os.makedirs(os.path.dirname(tis_file), exist_ok=True)
            await download.save_as(tis_file)
            log_callback(f"[Victory] TIS PDF downloaded: {os.path.basename(tis_file)}")
            
            # Close dialog if open
            try:
                close_dialog = compliance_page.locator("//button[contains(text(), 'Close') or contains(text(), 'Cancel') or @aria-label='Close']").first
                if await close_dialog.is_visible(timeout=2000):
                    await close_dialog.click()
            except Exception:
                pass
                
        except Exception as e:
            log_callback(f"[Error] Failed to download TIS PDF: {e}")
 
        # 2. AIS Download (PDF & JSON)
        log_callback("[AIS] Preparing download for Annual Information Statement...")
        await update_browser_status(compliance_page, "Compliance: Downloading AIS PDF...")
        try:
            # Click download in the AIS section
            ais_download_btn = compliance_page.locator("//div[contains(@class, 'ais') or contains(text(), 'Annual Information Statement') or contains(text(), 'AIS')]//following::button[contains(., 'Download') or @title='Download'] | //button[contains(@id, 'ais') or contains(@class, 'ais') and contains(@class, 'download')]").first
            if not await ais_download_btn.is_visible(timeout=5000):
                # Fallback to second general download icon
                ais_download_btn = compliance_page.locator("//button[contains(., 'Download') or @title='Download']").nth(1)
                
            await ais_download_btn.click()
            await asyncio.sleep(1.5)
 
            # 2a. AIS PDF Download
            pdf_select = compliance_page.locator("//button[contains(., 'PDF') or contains(text(), 'PDF')] | //a[contains(., 'PDF')]").first
            async with compliance_page.expect_download() as download_info_pdf:
                if await pdf_select.is_visible(timeout=3000):
                    await pdf_select.click()
                else:
                    await compliance_page.locator(".modal-body button, button:has-text('Download')").first.click()
            
            download_pdf = await download_info_pdf.value
            ais_pdf_file = os.path.join(download_dir, f"AIS_AY_{assessment_year.replace('-', '_')}.pdf")
            await download_pdf.save_as(ais_pdf_file)
            log_callback(f"[Victory] AIS PDF downloaded: {os.path.basename(ais_pdf_file)}")
            
            await asyncio.sleep(1)
 
            # Re-click AIS download button to fetch JSON if needed
            # (or check if modal is still open and contains JSON option)
            await update_browser_status(compliance_page, "Compliance: Downloading AIS JSON...")
            json_select = compliance_page.locator("//button[contains(., 'JSON') or contains(text(), 'JSON')] | //a[contains(., 'JSON')]").first
            if not await json_select.is_visible(timeout=2000):
                await ais_download_btn.click()
                await asyncio.sleep(1)
                json_select = compliance_page.locator("//button[contains(., 'JSON') or contains(text(), 'JSON')] | //a[contains(., 'JSON')]").first
                
            async with compliance_page.expect_download() as download_info_json:
                await json_select.click()
                
            download_json = await download_info_json.value
            ais_json_file = os.path.join(download_dir, f"AIS_AY_{assessment_year.replace('-', '_')}.json")
            await download_json.save_as(ais_json_file)
            log_callback(f"[Victory] AIS JSON downloaded: {os.path.basename(ais_json_file)}")
            await update_browser_status(compliance_page, "Compliance: All Downloads Completed!")
            await asyncio.sleep(1)
 
            # Close dialog if open
            try:
                close_dialog = compliance_page.locator("//button[contains(text(), 'Close') or contains(text(), 'Cancel') or @aria-label='Close']").first
                if await close_dialog.is_visible(timeout=2000):
                    await close_dialog.click()
            except Exception:
                pass
 
        except Exception as e:
            log_callback(f"[Error] Failed to download AIS files: {e}")
 
        # Close the Compliance Portal tab
        await compliance_page.close()
        return True
        
    except Exception as e:
        log_callback(f"[Error] Failed to download AIS/TIS: {e}")
        return False
