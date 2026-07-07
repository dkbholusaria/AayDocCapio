import os, asyncio, re
from playwright.async_api import Page
from automation.downloader import update_browser_status


async def _open_hamburger(page: Page, log_callback):
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)
    except Exception:
        pass
    for sel in ("#hamburgerOpen", "button[aria-label*='menu' i]", ".hamburger"):
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=500):
                log_callback(f"[168] Opening hamburger menu: {sel}")
                try:
                    await btn.click(timeout=3000)
                except Exception:
                    await btn.click(force=True, timeout=3000)
                await asyncio.sleep(1)
                return
        except Exception:
            continue


async def _enable_flutter_semantics(page: Page, log_callback):
    try:
        await page.evaluate(
            "document.querySelector('flt-semantics-placeholder')?.click()"
        )
        await asyncio.sleep(2)
        count = await page.locator("flt-semantics").count()
        log_callback(f"[168] Flutter semantics enabled — {count} flt-semantics element(s) found.")
        return count > 0
    except Exception as e:
        log_callback(f"[168] Could not enable Flutter semantics: {e}")
        return False


async def _log_semantics(page: Page, log_callback):
    try:
        elements = page.locator("flt-semantics[aria-label]")
        count = await elements.count()
        log_callback(f"[168] --- Semantics ({count} elements) ---")
        for i in range(min(count, 60)):
            el = elements.nth(i)
            lbl = await el.get_attribute("aria-label")
            role = await el.get_attribute("role") or ""
            box = await el.bounding_box()
            bstr = f"rect=({box['x']:.0f},{box['y']:.0f} {box['width']:.0f}×{box['height']:.0f})" if box else "rect=none"
            if lbl:
                log_callback(f"[168]   [{i}] role={role or'—'} {bstr} label={lbl!r}")
        log_callback(f"[168] --- End semantics ---")
    except Exception as e:
        log_callback(f"[168] Semantics dump failed: {e}")


async def _js_tap(page: Page, x: float, y: float, log_callback):
    """
    Dispatch touch+mouse events on the Flutter canvas (inside flt-glass-pane shadow DOM).
    Used for dropdown and listbox interactions where page.mouse.click() doesn't reach Flutter.
    """
    result = await page.evaluate(f"""() => {{
        const gp = document.querySelector('flt-glass-pane');
        if (!gp) return 'no flt-glass-pane';
        const target = gp.shadowRoot?.querySelector('canvas') || gp.shadowRoot?.firstElementChild || gp;
        const base = {{
            bubbles: true, cancelable: true, composed: true,
            clientX: {x}, clientY: {y},
            screenX: {x}, screenY: {y},
        }};
        target.dispatchEvent(new PointerEvent('pointermove', {{...base, pointerId:1, pointerType:'touch', isPrimary:true, pressure:0}}));
        target.dispatchEvent(new PointerEvent('pointerdown', {{...base, pointerId:1, pointerType:'touch', isPrimary:true, pressure:1}}));
        target.dispatchEvent(new MouseEvent('mousedown', {{...base, button:0, buttons:1}}));
        target.dispatchEvent(new PointerEvent('pointerup', {{...base, pointerId:1, pointerType:'touch', isPrimary:true, pressure:0}}));
        target.dispatchEvent(new MouseEvent('mouseup',  {{...base, button:0, buttons:0}}));
        target.dispatchEvent(new MouseEvent('click',    {{...base, button:0, buttons:0}}));
        return target.tagName;
    }}""")
    log_callback(f"[168] JS tap on {result} at ({x:.0f}, {y:.0f})")


async def _click_form168_card(page: Page, log_callback):
    """Click the Form 168 card on the TRACES 2.0 auth bridge dashboard by coordinates."""
    dims = await page.evaluate("""() => ({
        w: document.querySelector('flutter-view')?.clientWidth || window.innerWidth,
        h: document.querySelector('flutter-view')?.clientHeight || window.innerHeight
    })""")
    w, h = dims["w"], dims["h"]
    x = int(w * 0.264)
    y = int(h * 0.405)
    log_callback(f"[168] Canvas {w}×{h} — clicking Form 168 card at ({x}, {y})")
    await page.mouse.move(x, y)
    await asyncio.sleep(0.2)
    await page.mouse.click(x, y)


async def _select_year(page: Page, tax_year: str, log_callback):
    """Open the Tax Year dropdown and select the target year via JS tap on canvas."""
    # Open dropdown — JS tap works for this Flutter widget
    el = page.locator("flt-semantics[aria-label*='Select option']").first
    await el.wait_for(state="attached", timeout=10000)
    box = await el.bounding_box()
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    log_callback(f"[168] Opening dropdown at ({cx:.0f}, {cy:.0f})")
    await _js_tap(page, cx, cy, log_callback)
    await asyncio.sleep(2.0)

    # Select the listbox item — it appears below the dropdown with a "results available" label
    listbox_el = page.locator("flt-semantics[aria-label*='results available']").first
    try:
        await listbox_el.wait_for(state="attached", timeout=3000)
        box = await listbox_el.bounding_box()
        if box and box["width"] > 0:
            item_cx = box["x"] + box["width"] / 2
            item_cy = box["y"] + box["height"] / 2
            log_callback(f"[168] Tapping year option at ({item_cx:.0f}, {item_cy:.0f})")
            await _js_tap(page, item_cx, item_cy, log_callback)
            await asyncio.sleep(1.5)
            log_callback(f"[168] Tax Year selected: {tax_year}")
            return
    except Exception:
        pass

    # Fallback: keyboard
    log_callback(f"[168] Listbox not found — trying ArrowDown+Enter")
    await page.keyboard.press("ArrowDown")
    await asyncio.sleep(0.3)
    await page.keyboard.press("Enter")
    await asyncio.sleep(1.0)
    log_callback(f"[168] Tax Year selected (keyboard): {tax_year}")


async def _select_radio(page: Page, label_text: str, log_callback):
    """
    Select a radio button using page.mouse.move()+click() at confirmed coordinates.

    Radio button y positions confirmed visually via red-dot sweep (viewport 1600×900,
    page not scrolled). x=415 is the radio circle column.
      View Online:    y=430
      Download PDF:   y=465
      Download Excel: y=495
      Download Text:  y=525
    """
    radio_y = {
        "View Online":    430,
        "Download PDF":   465,
        "Download Excel": 495,
        "Download Text":  525,
    }
    y = radio_y.get(label_text)
    if y is None:
        raise Exception(f"Unknown radio option: {label_text}")
    log_callback(f"[168] Selecting radio '{label_text}' at (415, {y})")
    await page.mouse.move(415, y)
    await asyncio.sleep(0.15)
    await page.mouse.click(415, y)
    await asyncio.sleep(0.3)
    log_callback(f"[168] Radio selected: {label_text}")


async def _click_proceed(page: Page, log_callback):
    """Click the Proceed button using its live semantics bounding box."""
    el = page.locator("flt-semantics[aria-label*='Proceed']").first
    try:
        await el.wait_for(state="attached", timeout=5000)
        box = await el.bounding_box()
        if box and box["width"] > 0:
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            log_callback(f"[168] Clicking Proceed at ({cx:.0f}, {cy:.0f})")
            await _js_tap(page, cx, cy, log_callback)
        else:
            raise Exception("zero-size bbox")
    except Exception:
        log_callback("[168] Proceed fallback — JS tap at (709, 585)")
        await _js_tap(page, 709, 585, log_callback)
    log_callback("[168] Clicked Proceed — waiting for download...")
    await update_browser_status(page, "TRACES 2.0: Waiting for download...")
    await asyncio.sleep(3)


async def download_168(
    page: Page,
    tax_year: str,
    download_dir: str,
    log_callback,
    pan: str = "",
    dob: str = "",  # noqa: ARG001 — kept for call-site compatibility with download_26as signature
) -> tuple[bool, str, str]:
    """
    Download Form 168/Annual Tax Statement from TRACES 2.0 (Flutter/CanvasKit web app).

    Flow:
      1. ITD portal: e-File > Income Tax Returns > View Form 168 → new tab
      2. TRACES 2.0 auth bridge dashboard → click Form 168 card → form screen
      3. Enable Flutter semantics, select Tax Year (JS tap on canvas)
      4. Select each download type by radio button (page.mouse.click at confirmed y)
      5. Click Proceed (JS tap via semantics bbox) → expect_download
    """
    traces2_page = None
    try:
        await _open_hamburger(page, log_callback)

        try:
            await page.locator(".customLoaderBackdrop").wait_for(state="hidden", timeout=30000)
        except Exception:
            pass

        log_callback("[168] Hovering over e-File menu...")
        for _attempt in range(4):
            try:
                efile = page.locator("//*[normalize-space(.)='e-File']").first
                await efile.wait_for(state="visible", timeout=30000)
                await efile.hover(timeout=10000)
                break
            except Exception:
                if _attempt == 3:
                    raise
                log_callback(f"[168] e-File menu not ready (attempt {_attempt + 1}/4) — waiting...")
                try:
                    await page.keyboard.press("Escape")
                    await page.evaluate("window.scrollTo(0, 0)")
                except Exception:
                    pass
                await asyncio.sleep(5)
        await asyncio.sleep(1.0)

        log_callback("[168] Hovering over Income Tax Returns...")
        returns = page.locator("//*[text()='Income Tax Returns']").first
        await returns.wait_for(state="visible", timeout=30000)
        await returns.hover()
        await asyncio.sleep(1.0)

        log_callback("[168] Clicking View Form 168 — waiting for TRACES 2.0 to load...")
        await update_browser_status(page, "168: Opening TRACES 2.0 portal...")
        view_168 = page.locator("button.mat-mdc-menu-item", has_text="View Form 168, Income Tax Act 2025").first
        await view_168.wait_for(state="visible", timeout=30000)

        try:
            async with page.context.expect_page(timeout=40000) as new_page_info:
                await view_168.click()
                try:
                    confirm_btn = page.locator("button", has_text=re.compile(r"confirm|proceed", re.IGNORECASE)).first
                    await confirm_btn.wait_for(state="visible", timeout=4000)
                    await confirm_btn.click()
                    log_callback("[168] Confirmed TRACES 2.0 redirect popup.")
                except Exception:
                    pass
            traces2_page = await new_page_info.value
            await traces2_page.wait_for_load_state("domcontentloaded", timeout=40000)
            log_callback("[168] TRACES 2.0 opened in a new tab.")
        except Exception:
            traces2_page = page
            await page.wait_for_load_state("domcontentloaded", timeout=40000)
            log_callback("[168] TRACES 2.0 loaded in the same tab.")

        log_callback(f"[168] TRACES 2.0 URL: {traces2_page.url}")
        await update_browser_status(traces2_page, "TRACES 2.0: Connected.")

        screen = await traces2_page.evaluate("() => ({w: screen.width, h: screen.height})")
        await traces2_page.set_viewport_size({"width": screen["w"], "height": screen["h"]})

        if "authBridge" in traces2_page.url or "dashboard" in traces2_page.url:
            log_callback("[168] Auth bridge dashboard — clicking Form 168 card...")
            await update_browser_status(traces2_page, "TRACES 2.0: Navigating to Form 168...")
            for _attempt in range(5):
                await asyncio.sleep(3)
                await _click_form168_card(traces2_page, log_callback)
                await asyncio.sleep(3)
                if "authBridge" not in traces2_page.url and "dashboard" not in traces2_page.url:
                    break
                log_callback(f"[168] Still on dashboard after attempt {_attempt + 1} — retrying...")
            await traces2_page.wait_for_load_state("domcontentloaded", timeout=30000)
            log_callback(f"[168] Now at: {traces2_page.url}")

        await update_browser_status(traces2_page, "TRACES 2.0: Loading Form 168 screen...")
        await _enable_flutter_semantics(traces2_page, log_callback)
        await _log_semantics(traces2_page, log_callback)

        ty_str = tax_year.replace("-", "_")
        prefix = f"{pan}-" if pan else ""
        os.makedirs(download_dir, exist_ok=True)

        # ── Select Tax Year (once — persists for all downloads) ──────────────
        log_callback(f"[168] Selecting Tax Year: {tax_year}")
        await update_browser_status(traces2_page, f"TRACES 2.0: Selecting TY {tax_year}...")
        await _select_year(traces2_page, tax_year, log_callback)

        # ── PDF download ──────────────────────────────────────────────────────
        log_callback("[168] Selecting Download PDF...")
        await update_browser_status(traces2_page, "TRACES 2.0: Downloading PDF...")
        await _select_radio(traces2_page, "Download PDF", log_callback)
        output_pdf = os.path.join(download_dir, f"{prefix}168-{ty_str}.pdf")
        async with traces2_page.expect_download(timeout=60000) as dl_info:
            await _click_proceed(traces2_page, log_callback)
        await (await dl_info.value).save_as(output_pdf)
        log_callback(f"[Victory] Form 168 PDF downloaded: {os.path.basename(output_pdf)}")
        await asyncio.sleep(1)

        # ── Excel download (ITD native) ───────────────────────────────────────
        _saved_xls = ""
        try:
            log_callback("[168] Selecting Download Excel...")
            await update_browser_status(traces2_page, "TRACES 2.0: Downloading Excel...")
            await _select_radio(traces2_page, "Download Excel", log_callback)
            output_xls = os.path.join(download_dir, f"{prefix}168-{ty_str}-itd.xlsx")
            async with traces2_page.expect_download(timeout=60000) as xls_dl_info:
                await _click_proceed(traces2_page, log_callback)
            await (await xls_dl_info.value).save_as(output_xls)
            log_callback(f"[Victory] Form 168 Excel (ITD) downloaded: {os.path.basename(output_xls)}")
            _saved_xls = output_xls
        except Exception as xls_err:
            log_callback(f"[Warning] Excel download failed: {xls_err}")
        await asyncio.sleep(1)

        # ── TXT download ──────────────────────────────────────────────────────
        _saved_txt = ""
        tmp_path = ""
        try:
            log_callback("[168] Selecting Download Text...")
            await update_browser_status(traces2_page, "TRACES 2.0: Downloading TXT...")
            await _select_radio(traces2_page, "Download Text", log_callback)
            output_txt = os.path.join(download_dir, f"{prefix}168-{ty_str}.txt")
            tmp_path = output_txt + ".download"
            async with traces2_page.expect_download(timeout=60000) as txt_dl_info:
                await _click_proceed(traces2_page, log_callback)
            await (await txt_dl_info.value).save_as(tmp_path)
            os.replace(tmp_path, output_txt)
            log_callback(f"[Victory] Form 168 TXT downloaded: {os.path.basename(output_txt)}")
            _saved_txt = output_txt
        except Exception as txt_err:
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            log_callback(f"[Warning] TXT download failed: {txt_err}")

        await update_browser_status(traces2_page, "TRACES 2.0: Form 168 Download Complete!")
        await asyncio.sleep(1)
        await traces2_page.close()
        txt_warn = "" if _saved_txt else "PDF saved but TXT download failed"
        return True, txt_warn, _saved_txt

    except Exception as e:
        err = str(e)
        log_callback(f"[Error] Failed to download Form 168: {err}")
        if traces2_page:
            try:
                await traces2_page.close()
            except Exception:
                pass
        if "Timeout" in err or "timeout" in err:
            if "e-File" in err or "normalize-space" in err:
                reason = "Timed out — ITD dashboard still loading (try again)"
            elif "Flutter" in err or "flt-semantics" in err:
                reason = "Timed out waiting for TRACES 2.0 Flutter UI (try again)"
            else:
                reason = "Timed out waiting for portal response (try again)"
        elif "net::" in err.lower():
            reason = "Network error — check internet connection"
        elif "Target page" in err or "browser has been closed" in err:
            reason = "Browser closed unexpectedly"
        else:
            reason = err[:80] if len(err) <= 80 else err[:77] + "..."
        return False, reason, ""
