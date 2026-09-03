"""
automation/downloader_challans.py
===================================
F-61 — Download tax payment challans from the ITD e-Filing portal's
e-Pay Tax > Payment History section.

Confirmed portal flow (from live screenshots, see
PlansofThisProject/F-61_tax_challan_download.md):
  1. e-File > e-Pay Tax (direct click, no submenu hover — a sibling of
     "Income Tax Returns", not nested under it).
  2. "Select Applicable Income Tax Act" landing page — Income-tax Act, 1961
     (AY years) or Income-tax Act, 2025 (TY years) — then Continue.
  3. Payment History tab (of Saved Drafts / Generated Challans / Payment
     History).
  4. Filter panel: Assessment Year (or Tax Year), scopes the table to one
     year instead of paging through everything.
  5. Per-row ⋮ actions menu: Download / Copy / View Details.

UNCONFIRMED live: several selectors below (Act radio hit-target, Filter
panel's year control, the table/row/pager markup, and the ⋮ actions menu)
are principled best-effort guesses following patterns already confirmed
elsewhere on this same Angular portal (see
automation/downloader_filed_returns.py's _apply_ay_filter/_pager_arrow_enabled)
— not yet verified against a live e-Pay Tax run. Refine here first if a
step fails; each guess is called out at the point it's made.
"""
import asyncio
import os
import re

from playwright.async_api import Page

from automation.downloader import update_browser_status, make_step_logger
from automation._nav_helpers import open_hamburger
from automation.diagnostics import capture_failure
from automation.pdf_unlocker import unlock_pdf


async def _first_visible(locator, timeout_ms: int = 10000):
    """Given a Playwright locator that can match more than one element where
    only one is genuinely visible/interactable, poll until one becomes
    visible and return that specific nth() sub-locator (or None on timeout).
    Confirmed live: the e-Pay Tax Payment History filter panel and the
    Saved Drafts tab's own filter panel both keep an "Assessment Year"
    mat-select mounted at all times (one per tab, only one ever visible),
    both matching the same `formcontrolname='assessmentYear'` selector —
    `.first` picked whichever sorts first in DOM order regardless of which
    tab was actually open, not necessarily the visible one."""
    waited_ms = 0
    step_ms = 500
    while waited_ms < timeout_ms:
        count = await locator.count()
        for i in range(count):
            try:
                if await locator.nth(i).is_visible():
                    return locator.nth(i)
            except Exception:
                continue
        await asyncio.sleep(step_ms / 1000)
        waited_ms += step_ms
    return None


async def _click_visible_exact_text(page: Page, tag: str, text: str, log_callback, prefix: str,
                                     timeout_ms: int = 20000, prefer_last: bool = False) -> None:
    """Confirmed live (twice): this portal keeps several hidden
    modal-dismiss buttons mounted on the page that share the exact same
    text as a real, visible action button — first a "Continue Session"
    timeout-warning button matched a substring `has-text('Continue')`
    locator, then even after switching to an exact-text match, a second
    hidden `data-dismiss="modal"` button with the literal text "Continue"
    still collided with the real "Continue" button on the Act-selection
    page. DOM order (what `.first` picks) doesn't correlate with which one
    is actually visible, since modals are typically portaled elsewhere in
    the tree — so this polls all exact-text matches and clicks whichever
    one is visible, rather than trusting `.first`.

    `prefer_last`: when MORE THAN ONE match can be genuinely visible at the
    same time (e.g. a toolbar "Filter" button behind an open "Filter By"
    popup whose own apply button is also labeled "Filter"), pick the LAST
    visible match instead of the first — Angular CDK overlay popups are
    typically appended after existing page content in DOM order, so their
    controls sort after whatever opened them."""
    locator = page.locator(f"//{tag}[normalize-space(.)='{text}']")
    waited_ms = 0
    step_ms = 500
    while waited_ms < timeout_ms:
        count = await locator.count()
        visible_indices = []
        for i in range(count):
            try:
                if await locator.nth(i).is_visible():
                    visible_indices.append(i)
            except Exception:
                continue
        if visible_indices:
            target_i = visible_indices[-1] if prefer_last else visible_indices[0]
            await locator.nth(target_i).click()
            return
        await asyncio.sleep(step_ms / 1000)
        waited_ms += step_ms
    await capture_failure(page, log_callback, f"{prefix}_{text.replace(' ', '_')}_no_visible_match")
    raise TimeoutError(f"No visible '{text}' {tag} found within {timeout_ms}ms")


async def _click_efile_challans(page: Page, log_callback) -> None:
    """See automation/_nav_helpers.py's hover_to_income_tax_returns() for the
    full writeup on why e-File must be opened via click (not hover) and why
    this retries. e-Pay Tax sits directly under e-File as a sibling of
    "Income Tax Returns" — just a click once the top-level menu is open,
    no submenu hover needed."""
    for _attempt in range(4):
        try:
            efile = page.locator("//*[normalize-space(.)='e-File']").first
            await efile.wait_for(state="visible", timeout=30000)
            await efile.click(timeout=10000)
            return
        except Exception:
            if _attempt == 3:
                await capture_failure(page, log_callback, "CHALLAN_efile_click_failed")
                raise
            log_callback(f"[CHALLAN] e-File menu not ready (attempt {_attempt + 1}/4) — waiting...")
            try:
                await page.keyboard.press("Escape")
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            await asyncio.sleep(5)


async def navigate_to_epay_tax_act(page: Page, log_callback, year_type: str) -> Page:
    """One-time navigation per Act group: e-File > e-Pay Tax > select
    Income-tax Act (1961 for AY years, 2025 for TY years) > Continue,
    landing on the e-Pay Tax dashboard (Saved Drafts / Generated Challans /
    Payment History tabs, "+ New Payment" button). Shared by
    automation/downloader_challans.py's own Payment-History-tab flow (F-61)
    and automation/challan_generator.py's New-Payment flow (F-64) — both
    need this exact same Act-selection dance and nothing past it differs.

    F-14 (multi-year): this is the expensive/fragile part, so it runs ONCE
    per client per Act group; callers loop/branch afterward on this same
    already-open page — same shape as 26AS/Form 168's TRACES-1.0-vs-2.0
    split, since the Act choice is likewise fixed for the whole navigation
    and can't be changed mid-session."""
    log_callback("[CHALLAN] Opening hamburger menu (if collapsed)...")
    await open_hamburger(page, log_callback, prefix="CHALLAN")

    try:
        await page.locator(".customLoaderBackdrop").wait_for(state="hidden", timeout=30000)
    except Exception:
        pass

    log_callback("[CHALLAN] Opening e-File menu...")
    await _click_efile_challans(page, log_callback)
    await asyncio.sleep(1.0)

    log_callback("[CHALLAN] Clicking e-Pay Tax...")
    # BUG FIX (2026-09-03): confirmed live — on a client's second/third
    # navigation to e-Pay Tax within the same run (e.g. retrying after a
    # mid-scan failure), the page is already on the e-Pay Tax dashboard from
    # the earlier navigation, whose component carries its own permanently
    # -hidden `<h1 hidden>e-Pay Tax</h1>`. A page-wide exact-text locator
    # matches that hidden heading (it sorts before the freshly-opened
    # dropdown menu, which is portaled into a `cdk-overlay-container` at the
    # very end of <body>) and `.first` locks onto it, so `wait_for(visible)`
    # timed out on every attempt — same root-cause class as the "Other Bank"
    # ancestor-div bug elsewhere in this file. Scope the search to the
    # currently-open e-File dropdown panel instead, and re-resolve it fresh
    # on each retry (the panel itself gets torn down/reopened between
    # attempts, so a locator captured once before the loop can go stale).
    for _attempt in range(4):
        try:
            menu_panel = page.locator(".mat-mdc-menu-panel").last
            epay_tax = menu_panel.get_by_text("e-Pay Tax", exact=True)
            await epay_tax.wait_for(state="visible", timeout=15000)
            break
        except Exception:
            if _attempt == 3:
                await capture_failure(page, log_callback, "CHALLAN_epay_tax_click_failed")
                raise
            log_callback(f"[CHALLAN] e-Pay Tax not ready (attempt {_attempt + 1}/4) — reopening e-File...")
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(1)
            except Exception:
                pass
            await _click_efile_challans(page, log_callback)
            await asyncio.sleep(1.0)
    await epay_tax.click()
    await page.wait_for_load_state("domcontentloaded", timeout=40000)
    await asyncio.sleep(1.0)

    # "Select Applicable Income Tax Act" landing page.
    # UNCONFIRMED exact selector: matched by the distinguishing act-year
    # text inside each radio option's own label/container.
    act_text = "Income-tax Act, 2025" if year_type == "TY" else "Income-tax Act, 1961"
    log_callback(f"[CHALLAN] Selecting '{act_text}'...")
    act_option = page.locator(f"//*[contains(text(),'{act_text}')]").first
    await act_option.wait_for(state="visible", timeout=20000)
    await act_option.click()
    await asyncio.sleep(0.3)

    log_callback("[CHALLAN] Clicking Continue...")
    await _click_visible_exact_text(page, "button", "Continue", log_callback, "CHALLAN")
    await page.wait_for_load_state("domcontentloaded", timeout=30000)
    await asyncio.sleep(1.0)

    return page


async def _navigate_to_payment_history(page: Page, log_callback, year_type: str) -> Page:
    """F-61: e-Pay Tax dashboard > Payment History tab, on top of the shared
    Act-selection flow in navigate_to_epay_tax_act()."""
    await navigate_to_epay_tax_act(page, log_callback, year_type)

    log_callback("[CHALLAN] Clicking Payment History tab...")
    payment_history_tab = page.locator("//*[normalize-space(.)='Payment History']").first
    await payment_history_tab.wait_for(state="visible", timeout=20000)
    await payment_history_tab.click()
    await asyncio.sleep(1.0)

    return page


async def _apply_year_filter(payment_history_page: Page, year_value: str, step,
                              previous_year: str | None = None) -> bool:
    """Opens the Filter By panel and selects the target Assessment/Tax Year,
    then applies it — modeled on
    automation/downloader_filed_returns.py's _apply_ay_filter(), which uses
    the same Angular Material building blocks elsewhere on this portal.
    UNCONFIRMED live: the e-Pay Tax filter panel's own exact markup hasn't
    been inspected directly yet. Falls back to a full page-walk scan on
    failure, same pattern as Filed Returns.

    F-14 (multi-year): `previous_year`, if given, is unchecked before the
    new year is selected, same reasoning as Filed Returns' equivalent."""
    try:
        step("Locating Filter button (picking whichever match is actually visible)")
        # Confirmed live: same "multiple elements share this exact text,
        # only one is visible" issue as the Continue button on the
        # Act-selection page — a plain `.first` locked onto a hidden
        # duplicate. See _click_visible_exact_text's docstring.
        await _click_visible_exact_text(payment_history_page, "button", "Filter", step, "CHALLAN")
        await asyncio.sleep(0.5)

        # Confirmed live: two "Assessment Year" mat-selects are mounted at
        # once — one in Payment History's own filter panel (visible), one
        # belonging to the Saved Drafts tab's filter panel (present but
        # hidden). Both match formcontrolname='assessmentYear', so `.first`
        # was silently grabbing the wrong (hidden) one. Poll for whichever
        # instance is actually visible instead.
        step("Locating the visible Assessment/Tax Year selector")
        year_select_all = payment_history_page.locator(
            "mat-select[formcontrolname='assessmentYear'], mat-select[formcontrolname='taxYear']"
        )
        year_select = await _first_visible(year_select_all, timeout_ms=10000)
        if year_select is None:
            raise RuntimeError("No visible Assessment/Tax Year selector found")
        await year_select.click()

        if previous_year and previous_year != year_value:
            try:
                prev_option = payment_history_page.locator(
                    f"mat-option:has-text('{previous_year}')"
                ).first
                if await prev_option.count() > 0:
                    is_checked = await prev_option.locator(".mat-pseudo-checkbox-checked").count() > 0
                    if is_checked:
                        step(f"Unchecking previous year filter: {previous_year}")
                        await prev_option.click()
                        await asyncio.sleep(0.3)
            except Exception as e:
                step(f"Could not uncheck previous year filter option (continuing): {e}")

        option_selector = f"mat-option:has-text('{year_value}')"
        step(f"Waiting for year option: {option_selector}")
        year_option = payment_history_page.locator(option_selector).first
        await year_option.wait_for(state="visible", timeout=10000)
        await year_option.click()

        await payment_history_page.keyboard.press("Escape")
        await asyncio.sleep(0.3)

        # The popup's own apply button is also labeled "Filter" (confirmed
        # via screenshot), and the toolbar button that opened this popup
        # may still be visible behind it — so both could match at once.
        # prefer_last=True picks the popup's own button (see docstring).
        step("Clicking popup's Filter (apply) button")
        await _click_visible_exact_text(payment_history_page, "button", "Filter", step, "CHALLAN",
                                         prefer_last=True)
        await asyncio.sleep(1.5)
        step(f"Year filter applied successfully: {year_value}")
        return True
    except Exception as e:
        step(f"Year filter failed: {e} — will fall back to full page scan")
        try:
            await payment_history_page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            await payment_history_page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        except Exception:
            pass
        return False


async def _pager_next_enabled(next_btn, step) -> bool:
    """Confirmed live: unlike Filed Returns' <img aria-disabled> pager, this
    table's pager buttons are real <button disabled> elements (the disabled
    state adds a literal `disabled="true"` attribute and a
    `mat-mdc-button-disabled` class), so Playwright's native is_enabled()
    works directly — no custom attribute check needed."""
    try:
        if await next_btn.count() == 0:
            return False
        enabled = await next_btn.is_enabled()
        step(f"Pager 'next' button enabled={enabled}")
        return enabled
    except Exception as e:
        step(f"Pager 'next' button check failed: {e}")
        return False


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (text or "").strip()).strip("_") or "Payment"


async def _download_challans_for_year(
    payment_history_page: Page,
    year_value: str,
    download_dir: str,
    log_callback,
    pan: str = "",
    dob: str = "",
    previous_year: str | None = None,
) -> tuple[bool, str, list[dict]]:
    """Downloads every challan for ONE Assessment/Tax Year, assuming
    `_navigate_to_payment_history()` has already landed on the Payment
    History tab for the correct Act. Challans are independent payments (not
    revisions of one another the way ITR filings are), so there's no
    "filing scope" concept here — every payment for the year is fetched,
    saved flat into a "Tax Challans" subfolder keyed by CIN (unique per
    payment)."""
    step = make_step_logger(log_callback, "CHALLAN")
    try:
        step(f"Starting Challan download — year={year_value}, pan={'set' if pan else 'blank'}")
        challan_dir = os.path.join(download_dir, "Tax Challans")
        os.makedirs(challan_dir, exist_ok=True)
        prefix = f"{pan}-" if pan else ""

        # Confirmed live: the "Filter By" panel is NOT a real modal — Escape
        # does not close it, and once opened it stays on screen as an
        # absolutely-positioned overlay that physically blocks clicks on
        # the rows underneath it (confirmed: row action-menu clicks failed
        # with "filter-section subtree intercepts pointer events" even
        # AFTER giving up on the filter and falling back to a full scan).
        # Since the plain page-walk scan below already reliably finds the
        # right rows via the Assessment Year column, the filter is skipped
        # entirely for now rather than risk leaving it stuck open — this
        # trades a paging-cost optimization for reliability. _apply_year_filter()
        # is kept below for when the panel's dismiss behavior is figured out.
        step("Skipping Filter panel — scanning all pages directly")

        # Confirmed live (full HTML capture): this is an ag-Grid table, not
        # a semantic <table>. Data rows are div[role="row"] carrying the
        # "ag-row" class (the header row also has role="row" but a
        # different "ag-header-row" class, so scoping to ".ag-row"
        # specifically excludes it). Each cell is a div[role="gridcell"]
        # with a col-id attribute: cin / brnNum / assessmentYear /
        # paymentType / amount / paymentTime / "0" (Actions).
        next_page_btn = payment_history_page.locator("button:has(img[src*='nextPage'])").first

        saved_files: list[dict] = []
        warnings: list[str] = []
        found_any = False
        seen_cins: set = set()

        for _page_num in range(20):  # hard cap: confirmed up to 18 pages of history in testing
            step(f"Scanning Payment History page {_page_num}")
            rows = payment_history_page.locator("div.ag-center-cols-container > div.ag-row")
            row_count = await rows.count()
            step(f"Found {row_count} row(s) on this page")
            for i in range(row_count):
                row = rows.nth(i)
                # Confirmed live: the year column's col-id differs by Act —
                # "assessmentYear" under the 1961 Act table, but the 2025
                # Act's table (labeled "Tax Year" instead of "Assessment
                # Year") uses a different one; a hardcoded "assessmentYear"
                # matched nothing and hung until timeout on a TY account.
                # Try both rather than guess which one this table uses.
                year_cell = row.locator('[col-id="assessmentYear"], [col-id="taxYear"]').first
                try:
                    ay_text = (await year_cell.inner_text()).strip()
                except Exception as e:
                    step(f"Row {i}: could not read Assessment/Tax Year cell ({e})")
                    continue
                if ay_text != year_value:
                    continue

                try:
                    cin = (await row.locator('[col-id="cin"]').inner_text()).strip()
                except Exception:
                    cin = f"row{i}"
                if cin in seen_cins:
                    continue
                seen_cins.add(cin)
                found_any = True

                try:
                    payment_type = (await row.locator('[col-id="paymentType"]').inner_text()).strip()
                except Exception:
                    payment_type = ""

                try:
                    actions_btn = row.locator('[col-id="0"] .mat-mdc-menu-trigger').first
                    await actions_btn.click()
                    await asyncio.sleep(0.3)
                    # UNCONFIRMED exact text: the ⋮ menu's items (Download/
                    # Copy/View Details) render into a portaled CDK overlay
                    # only once opened — not present in a static HTML
                    # capture taken with the menu closed.
                    download_item = payment_history_page.locator("//*[normalize-space(.)='Download']").first
                    filename = f"{prefix}Challan-{year_value.replace('-', '_')}-{cin}-{_slug(payment_type)}.pdf"
                    output_path = os.path.join(challan_dir, filename)
                    async with payment_history_page.expect_download() as download_info:
                        await download_item.click()
                    await (await download_info.value).save_as(output_path)
                    step(f"[Victory] Challan downloaded: {os.path.basename(output_path)}")
                    if dob:
                        result = unlock_pdf(output_path, pan=pan, dob=dob, log=step)
                        if result.get("unlocked"):
                            step(f"[PDF Unlock] {os.path.basename(output_path)} unlocked")
                    saved_files.append({"cin": cin, "payment_type": payment_type, "path": output_path})
                except Exception as e:
                    step(f"[Warning] Challan download failed for row {i} (CIN {cin}): {e}")
                    warnings.append(f"Challan {cin} download failed: {e}")

            try:
                if await _pager_next_enabled(next_page_btn, step):
                    await next_page_btn.click()
                    await asyncio.sleep(1)
                else:
                    step("Next-page button disabled or absent — reached last page, stopping scan")
                    break
            except Exception as e:
                step(f"Next-page click failed ({e}) — stopping scan")
                break

        await update_browser_status(payment_history_page, "Challans: Download Complete!")
        step(f"Done: {len(saved_files)} file(s) saved, {len(warnings)} warning(s)")

        if not found_any:
            return False, f"No challans found for {year_value}", []
        if not saved_files:
            return False, "All challan downloads failed: " + "; ".join(warnings), []
        if warnings:
            return True, "; ".join(warnings), saved_files
        return True, "", saved_files

    except Exception as e:
        err = str(e)
        step(f"[Error] Failed to download Challans: {err}")
        if "Timeout" in err or "timeout" in err:
            reason = "Timed out — ITD dashboard still loading (try again)"
        elif "net::" in err.lower():
            reason = "Network error — check internet connection"
        elif "Target page" in err or "browser has been closed" in err:
            reason = "Browser closed unexpectedly"
        else:
            reason = err[:80] if len(err) <= 80 else err[:77] + "..."
        return False, reason, []


async def download_challans(
    page: Page,
    years: list[str],
    download_dir_for_year,
    log_callback,
    pan: str = "",
    dob: str = "",
    year_type: str = "AY",
    on_year_start=None,
) -> dict[str, tuple[bool, str, list[dict]]]:
    """F-14 (multi-year) entry point for ONE Act group — the Act selection
    is fixed for the whole navigation, so callers must invoke this once per
    year_type group (all-AY years in one call, all-TY years in another),
    same split as 26AS/Form 168's TRACES-1.0-vs-2.0 handling. Navigates to
    Payment History ONCE, then for each year in `years`: re-applies the
    year filter (unchecking whichever year was applied last) and downloads
    that year's challans into `download_dir_for_year(year)`.

    `on_year_start(year)`, if given, fires right before that year's
    download begins."""
    step = make_step_logger(log_callback, "CHALLAN")
    results: dict[str, tuple[bool, str, list[dict]]] = {}
    try:
        payment_history_page = await _navigate_to_payment_history(page, log_callback, year_type)
    except Exception as e:
        step(f"[Error] Could not reach Payment History: {e}")
        for y in years:
            results[y] = (False, f"Navigation failed: {e}", [])
        return results

    previous_year: str | None = None
    for year_value in years:
        if on_year_start:
            on_year_start(year_value)
        download_dir = download_dir_for_year(year_value)
        results[year_value] = await _download_challans_for_year(
            payment_history_page, year_value, download_dir, log_callback,
            pan=pan, dob=dob, previous_year=previous_year,
        )
        previous_year = year_value
    return results
