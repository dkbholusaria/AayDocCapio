import os, asyncio
from playwright.async_api import Page
from automation.downloader import update_browser_status


# Selectors tried in order for each UI element — portal HTML changes frequently
_AIS_NAV_SELECTORS = [
    "//*[normalize-space(.)='AIS']",
    "a:has-text('AIS')",
    "li:has-text('AIS') a",
]

_AIS_SUBTAB_SELECTORS = [
    "nav.sub-navbar a:has-text('AIS')",
    "a.nav-link:has-text('AIS')",
    "ul.nav a:has-text('AIS')",
    "li.nav-item:has-text('AIS') a",
    "a:has-text('AIS')",
]

_FY_TOGGLE_SELECTORS = [
    "button.dropdown-toggle",
    "[class*='dropdown'] button",
    "button:has-text('F.Y.')",
    "select",   # fallback if portal switched to <select>
]

_AIS_DETAIL_TAB_SELECTORS = [
    "button:has-text('Annual Information Statement')",
    "a:has-text('Annual Information Statement')",
    "li:has-text('Annual Information Statement') a",
    "[role='tab']:has-text('Annual Information Statement')",
    "div.tab:has-text('Annual Information Statement')",
    "span:has-text('Annual Information Statement')",
]

_TIS_DETAIL_TAB_SELECTORS = [
    "button:has-text('Taxpayer Information Summary')",
    "a:has-text('Taxpayer Information Summary')",
    "li:has-text('Taxpayer Information Summary') a",
    "[role='tab']:has-text('Taxpayer Information Summary')",
    "div.tab:has-text('Taxpayer Information Summary')",
    "span:has-text('Taxpayer Information Summary')",
]

_DOWNLOAD_BTN_SELECTORS = [
    "button[class*='dialog-outline-btn']:has-text('Download')",
    "button.btn-primary:has-text('Download')",
    "button:has-text('Download')",
    "a:has-text('Download')",
]


async def _click_first(page, selectors: list, label: str, timeout=10000):
    """Try each selector in order; click the first one that becomes visible."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.click()
            return sel
        except Exception:
            continue
    raise Exception(f"Could not find '{label}' — tried: {selectors}")


async def _wait_first(page, selectors: list, label: str, timeout=10000):
    """Return the first locator that becomes visible."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout)
            return loc
        except Exception:
            continue
    raise Exception(f"Could not find '{label}' — tried: {selectors}")


async def download_ais_tis(page: Page, fiscal_year: str, download_dir: str, log_callback, pan: str = "") -> bool:
    """
    fiscal_year: FY string like "2022-23" (one year behind the AY).
    The Compliance Portal shows F.Y. dropdowns, not AY.
    """
    compliance_page = None
    try:
        log_callback("[AIS/TIS] Opening Compliance Portal via AIS nav link...")
        await update_browser_status(page, "AIS/TIS: Opening Compliance Portal...")

        # Find and click the AIS nav item — opens Compliance Portal in a new tab
        ais_nav = None
        for sel in _AIS_NAV_SELECTORS:
            try:
                loc = page.locator(sel).first
                await loc.wait_for(state="visible", timeout=10000)
                ais_nav = loc
                break
            except Exception:
                continue
        if not ais_nav:
            raise Exception("AIS nav item not found on ITD dashboard.")

        try:
            async with page.context.expect_page(timeout=15000) as new_page_info:
                await ais_nav.click()
            compliance_page = await new_page_info.value
            await compliance_page.wait_for_load_state("domcontentloaded", timeout=30000)
            log_callback("[AIS/TIS] Compliance Portal opened in new tab.")
        except Exception:
            # Sometimes it navigates in the same tab
            compliance_page = page
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            log_callback("[AIS/TIS] Compliance Portal loaded in same tab.")

        await asyncio.sleep(3)  # Angular bootstrap time
        log_callback(f"[AIS/TIS] Portal URL: {compliance_page.url}")
        await update_browser_status(compliance_page, "Compliance Portal: Ready")

        # Dismiss any alert/popup that may appear on first load
        try:
            dismiss = compliance_page.locator(
                "button:has-text('OK'), button:has-text('Close'), button:has-text('Proceed'), "
                "button[aria-label='Close']"
            ).first
            await dismiss.wait_for(state="visible", timeout=4000)
            await dismiss.click()
            await asyncio.sleep(1)
            log_callback("[AIS/TIS] Dismissed portal popup.")
        except Exception:
            pass

        # Click the AIS sub-tab
        log_callback("[AIS/TIS] Navigating to AIS sub-tab...")
        try:
            await _click_first(compliance_page, _AIS_SUBTAB_SELECTORS, "AIS sub-tab", timeout=10000)
            await asyncio.sleep(2)
            log_callback("[AIS/TIS] AIS tab active.")
        except Exception as e:
            log_callback(f"[AIS/TIS] AIS sub-tab not found ({e}), continuing on current page...")

        await update_browser_status(compliance_page, "Compliance Portal: AIS page")

        # ── Select Financial Year ─────────────────────────────────────────────
        log_callback(f"[AIS/TIS] Selecting F.Y. {fiscal_year}...")
        await update_browser_status(compliance_page, f"Compliance Portal: Selecting FY {fiscal_year}...")
        try:
            # Try dropdown button
            fy_toggle = await _wait_first(
                compliance_page,
                ["button.dropdown-toggle", "button:has-text('F.Y.')", "[class*='dropdown'] button"],
                "FY dropdown toggle", timeout=8000)
            await fy_toggle.click()
            await asyncio.sleep(0.5)
            fy_option = compliance_page.locator(f".dropdown-item:has-text('{fiscal_year}')").first
            await fy_option.wait_for(state="visible", timeout=5000)
            await fy_option.click()
            log_callback(f"[AIS/TIS] F.Y. {fiscal_year} selected.")
        except Exception:
            # Fallback: <select> element
            try:
                sel_el = compliance_page.locator("select").first
                await sel_el.select_option(label=fiscal_year)
                log_callback(f"[AIS/TIS] F.Y. {fiscal_year} selected via <select>.")
            except Exception as fe:
                log_callback(f"[Warning] Could not select FY {fiscal_year}: {fe}")
        await asyncio.sleep(2)

        ay_str = fiscal_year.replace("-", "_")
        prefix = f"{pan}-" if pan else ""
        os.makedirs(download_dir, exist_ok=True)

        # ── AIS download ──────────────────────────────────────────────────────
        log_callback("[AIS/TIS] Clicking Annual Information Statement tab...")
        await update_browser_status(compliance_page, "Compliance Portal: Opening AIS detail...")
        try:
            await _click_first(compliance_page, _AIS_DETAIL_TAB_SELECTORS,
                                "Annual Information Statement tab", timeout=15000)
            await asyncio.sleep(2)
        except Exception as e:
            # Log visible text to help diagnose selector mismatch
            try:
                body_text = await compliance_page.locator("body").inner_text()
                log_callback(f"[AIS/TIS] Page text snippet: {body_text[:400]}")
            except Exception:
                pass
            raise Exception(f"Annual Information Statement tab not found: {e}")

        log_callback("[AIS/TIS] Clicking Download to open AIS download dialog...")
        await update_browser_status(compliance_page, "Compliance Portal: AIS download dialog...")
        dl_trigger = await _wait_first(compliance_page, _DOWNLOAD_BTN_SELECTORS, "Download button", timeout=10000)
        await dl_trigger.click()
        await asyncio.sleep(1)

        # Wait for download modal
        modal = None
        for modal_sel in [".modal.show", ".modal[style*='display: block']", "[role='dialog']", ".modal-dialog"]:
            try:
                m = compliance_page.locator(modal_sel).first
                await m.wait_for(state="visible", timeout=5000)
                modal = m
                break
            except Exception:
                continue

        if modal:
            log_callback("[AIS/TIS] Download modal open.")
            ais_pdf_file = os.path.join(download_dir, f"{prefix}AIS-{ay_str}.pdf")
            log_callback("[AIS/TIS] Downloading AIS PDF...")
            try:
                async with compliance_page.context.expect_download(timeout=30000) as dl_pdf:
                    await modal.locator("button:has-text('Download')").nth(0).click()
                await (await dl_pdf.value).save_as(ais_pdf_file)
                log_callback(f"[Victory] AIS PDF: {os.path.basename(ais_pdf_file)}")
            except Exception as e:
                log_callback(f"[Warning] AIS PDF download failed: {e}")

            ais_json_file = os.path.join(download_dir, f"{prefix}AIS-{ay_str}.json")
            log_callback("[AIS/TIS] Downloading AIS JSON...")
            try:
                async with compliance_page.context.expect_download(timeout=30000) as dl_json:
                    await modal.locator("button:has-text('Download')").nth(1).click()
                await (await dl_json.value).save_as(ais_json_file)
                log_callback(f"[Victory] AIS JSON: {os.path.basename(ais_json_file)}")
            except Exception as e:
                log_callback(f"[Warning] AIS JSON download failed: {e}")

            # Close modal
            try:
                await modal.locator(
                    "button[aria-label='Close'], button.close, button:has-text('×'), button:has-text('Close')"
                ).first.click()
                await asyncio.sleep(0.5)
            except Exception:
                pass
        else:
            # No modal — direct download
            ais_pdf_file = os.path.join(download_dir, f"{prefix}AIS-{ay_str}.pdf")
            log_callback("[AIS/TIS] No modal — attempting direct AIS download...")
            try:
                async with compliance_page.context.expect_download(timeout=30000) as dl_pdf:
                    await dl_trigger.click()
                await (await dl_pdf.value).save_as(ais_pdf_file)
                log_callback(f"[Victory] AIS PDF: {os.path.basename(ais_pdf_file)}")
            except Exception as e:
                log_callback(f"[Warning] AIS direct download failed: {e}")

        # ── TIS download ──────────────────────────────────────────────────────
        log_callback("[AIS/TIS] Clicking Taxpayer Information Summary tab...")
        await update_browser_status(compliance_page, "Compliance Portal: Opening TIS detail...")
        try:
            await _click_first(compliance_page, _TIS_DETAIL_TAB_SELECTORS,
                                "Taxpayer Information Summary tab", timeout=10000)
            await asyncio.sleep(2)
        except Exception as e:
            log_callback(f"[Warning] TIS tab not found: {e}")

        log_callback("[AIS/TIS] Clicking Download for TIS...")
        await update_browser_status(compliance_page, "Compliance Portal: TIS download...")
        tis_file = os.path.join(download_dir, f"{prefix}TIS-{ay_str}.pdf")
        try:
            tis_trigger = await _wait_first(compliance_page, _DOWNLOAD_BTN_SELECTORS, "TIS Download button", timeout=10000)
            await tis_trigger.click()
            await asyncio.sleep(1)

            # Check for modal
            tis_modal = None
            for modal_sel in [".modal.show", ".modal[style*='display: block']", "[role='dialog']"]:
                try:
                    m = compliance_page.locator(modal_sel).first
                    await m.wait_for(state="visible", timeout=3000)
                    tis_modal = m
                    break
                except Exception:
                    continue

            if tis_modal:
                async with compliance_page.context.expect_download(timeout=30000) as dl_tis:
                    await tis_modal.locator("button:has-text('Download')").nth(0).click()
                try:
                    await tis_modal.locator(
                        "button[aria-label='Close'], button.close, button:has-text('×')"
                    ).first.click()
                except Exception:
                    pass
            else:
                async with compliance_page.context.expect_download(timeout=30000) as dl_tis:
                    await tis_trigger.click()
            await (await dl_tis.value).save_as(tis_file)
            log_callback(f"[Victory] TIS PDF: {os.path.basename(tis_file)}")
        except Exception as tis_err:
            log_callback(f"[Warning] TIS download failed: {tis_err}")

        await update_browser_status(compliance_page, "Compliance Portal: All downloads complete!")
        await asyncio.sleep(1)
        await compliance_page.close()
        return True

    except Exception as e:
        log_callback(f"[Error] Failed to download AIS/TIS: {e}")
        if compliance_page:
            try:
                await compliance_page.close()
            except Exception:
                pass
        return False
