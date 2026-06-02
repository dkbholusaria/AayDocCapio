import os, asyncio
from playwright.async_api import Page
from automation.downloader import update_browser_status


async def download_ais_tis(page: Page, assessment_year: str, download_dir: str, log_callback, pan: str = "") -> bool:
    compliance_page = None
    try:
        log_callback("[AIS/TIS] Clicking AIS in top navigation to open Compliance Portal...")
        await update_browser_status(page, "AIS/TIS: Opening Compliance Portal...")

        # On the ITD portal the "AIS" nav item opens the Compliance Portal in a new tab
        ais_nav = page.locator("//*[normalize-space(.)='AIS']").first
        await ais_nav.wait_for(state="visible", timeout=15000)

        async with page.context.expect_page(timeout=15000) as new_page_info:
            await ais_nav.click()
        compliance_page = await new_page_info.value
        await compliance_page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(3)  # Angular needs time to bootstrap
        log_callback(f"[AIS/TIS] Compliance Portal loaded.")
        await update_browser_status(compliance_page, "Compliance Portal: Ready")

        # Click the "AIS" sub-tab in the top sub-navbar (Instructions | AIS)
        log_callback("[AIS/TIS] Clicking AIS tab...")
        ais_tab = compliance_page.locator("nav.sub-navbar a:has-text('AIS')").first
        await ais_tab.wait_for(state="visible", timeout=15000)
        await ais_tab.click()
        await asyncio.sleep(2)
        log_callback("[AIS/TIS] AIS page loaded.")
        await update_browser_status(compliance_page, "Compliance Portal: AIS page")

        # ── Select Financial Year ─────────────────────────────────────────────
        # Dropdown shows "F.Y. 2025-26" format; assessment_year param is "2025-26"
        log_callback(f"[AIS/TIS] Selecting F.Y. {assessment_year}...")
        await update_browser_status(compliance_page, f"Compliance Portal: Selecting FY {assessment_year}...")
        fy_toggle = compliance_page.locator("button.dropdown-toggle").filter(has_text="F.Y.").first
        await fy_toggle.wait_for(state="visible", timeout=10000)
        await fy_toggle.click()
        await asyncio.sleep(0.5)
        fy_option = compliance_page.locator(f".dropdown-item:has-text('{assessment_year}')").first
        await fy_option.wait_for(state="visible", timeout=5000)
        await fy_option.click()
        await asyncio.sleep(2)

        ay_str = assessment_year.replace("-", "_")
        prefix = f"{pan}-" if pan else ""
        os.makedirs(download_dir, exist_ok=True)

        # ── AIS download ──────────────────────────────────────────────────────
        # Page has inner tabs: "Taxpayer Information Summary" | "Annual Information Statement"
        # Click "Annual Information Statement" tab to activate its view
        log_callback("[AIS/TIS] Clicking Annual Information Statement tab...")
        await update_browser_status(compliance_page, "Compliance Portal: Opening AIS detail...")
        ais_detail_tab = compliance_page.locator("button:has-text('Annual Information Statement')").first
        await ais_detail_tab.wait_for(state="visible", timeout=15000)
        await ais_detail_tab.click()
        await asyncio.sleep(1.5)

        # Click the blue "Download" button — this opens the download modal
        log_callback("[AIS/TIS] Clicking Download to open the AIS download dialog...")
        await update_browser_status(compliance_page, "Compliance Portal: AIS download dialog...")
        dl_trigger = compliance_page.locator(
            "button[class*='dialog-outline-btn']:has-text('Download'), "
            "button.btn-primary:has-text('Download')"
        ).first
        await dl_trigger.wait_for(state="visible", timeout=10000)
        await dl_trigger.click()
        await asyncio.sleep(1)

        # Modal opens with rows: AIS PDF | AIS JSON | ACF PDF
        # Wait for the modal to appear
        modal = compliance_page.locator(".modal.show, .modal[style*='display: block']").first
        await modal.wait_for(state="visible", timeout=5000)
        log_callback("[AIS/TIS] Download modal open.")

        # Row 0 → AIS PDF,  Row 1 → AIS JSON
        ais_pdf_file = os.path.join(download_dir, f"{prefix}AIS-{ay_str}.pdf")
        log_callback("[AIS/TIS] Downloading AIS PDF...")
        async with compliance_page.context.expect_download(timeout=30000) as dl_pdf:
            await modal.locator("button:has-text('Download')").nth(0).click()
        await (await dl_pdf.value).save_as(ais_pdf_file)
        log_callback(f"[Victory] AIS PDF downloaded: {os.path.basename(ais_pdf_file)}")

        ais_json_file = os.path.join(download_dir, f"{prefix}AIS-{ay_str}.json")
        log_callback("[AIS/TIS] Downloading AIS JSON...")
        async with compliance_page.context.expect_download(timeout=30000) as dl_json:
            await modal.locator("button:has-text('Download')").nth(1).click()
        await (await dl_json.value).save_as(ais_json_file)
        log_callback(f"[Victory] AIS JSON downloaded: {os.path.basename(ais_json_file)}")

        # Close the modal
        try:
            close_btn = modal.locator("button[aria-label='Close'], button.close, button:has-text('×')").first
            await close_btn.click()
            await asyncio.sleep(0.5)
        except Exception:
            pass

        # ── TIS download ──────────────────────────────────────────────────────
        log_callback("[AIS/TIS] Clicking Taxpayer Information Summary tab...")
        await update_browser_status(compliance_page, "Compliance Portal: Opening TIS detail...")
        tis_detail_tab = compliance_page.locator("button:has-text('Taxpayer Information Summary')").first
        await tis_detail_tab.wait_for(state="visible", timeout=10000)
        await tis_detail_tab.click()
        await asyncio.sleep(1.5)

        # Click Download button for TIS (same pattern — opens modal or direct download)
        log_callback("[AIS/TIS] Clicking Download to open TIS download dialog...")
        await update_browser_status(compliance_page, "Compliance Portal: TIS download dialog...")
        tis_trigger = compliance_page.locator(
            "button[class*='dialog-outline-btn']:has-text('Download'), "
            "button.btn-primary:has-text('Download')"
        ).first
        await tis_trigger.wait_for(state="visible", timeout=10000)

        tis_file = os.path.join(download_dir, f"{prefix}TIS-{ay_str}.pdf")
        try:
            # Try modal path first
            await tis_trigger.click()
            await asyncio.sleep(1)
            tis_modal = compliance_page.locator(".modal.show, .modal[style*='display: block']").first
            if await tis_modal.is_visible(timeout=3000):
                log_callback("[AIS/TIS] TIS download modal open.")
                async with compliance_page.context.expect_download(timeout=30000) as dl_tis:
                    await tis_modal.locator("button:has-text('Download')").nth(0).click()
                # Close TIS modal
                try:
                    await tis_modal.locator("button[aria-label='Close'], button.close, button:has-text('×')").first.click()
                except Exception:
                    pass
            else:
                # Direct download (no modal)
                async with compliance_page.context.expect_download(timeout=30000) as dl_tis:
                    await tis_trigger.click()
            await (await dl_tis.value).save_as(tis_file)
            log_callback(f"[Victory] TIS downloaded: {os.path.basename(tis_file)}")
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
