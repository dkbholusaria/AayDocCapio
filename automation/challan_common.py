"""
automation/challan_common.py
============================
Shared e-Pay Tax challan steps used by both the Income Tax generator
(F-64, automation/challan_generator.py) and the TDS/TCS generator
(F-4, automation/challan_generator_tds.py).

Everything here was moved verbatim from challan_generator.generate_challan
after it had been confirmed live — the detailed bug-history comments stayed
with the code so the reasons for each workaround are not lost.
"""
import asyncio
import os
import re

from automation.downloader_challans import _click_visible_exact_text


def _norm_bank_name(text: str) -> str:
    """Loose normalization for bank-name matching against dropdown options.

    Confirmed live (2026-09-02): the portal's real "Other Bank" option text
    differs from this app's static _NET_BANKING_EXTENDED list in small,
    inconsistent ways — casing ("Central Bank Of India" vs our "Central
    Bank of India"), "&" vs "And" ("Jammu And Kashmir Bank" vs "Jammu &
    Kashmir Bank"), and trailing "Limited"/"Ltd" suffixes present on the
    portal but not in our list ("City Union Bank Limited", "RBL Bank
    Limited"). An exact-text XPath match failed on "Central Bank Of India"
    even though the option was actually open and visible. Normalize both
    sides instead of trying to hardcode every portal wording exactly.
    """
    s = (text or "").strip().lower()
    s = s.replace("&", "and")
    s = re.sub(r"\s+(limited|ltd\.?)\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


async def _click_matching_option(
    scope, target_text: str, timeout: int = 10000,
    selector: str = "mat-option, [role='option']",
):
    """Find and click the visible element (matching `selector`) whose text
    matches target_text once both are loosely normalized (see
    _norm_bank_name) — tolerant of the casing/wording drift confirmed live
    between this app's bank-name lists and the portal's actual text.
    Defaults to open-dropdown options; pass selector="mat-radio-button" for
    a tile/radio group instead (confirmed live 2026-09-02: the primary bank
    tiles need the same tolerant matching as the "Other Bank" dropdown —
    an exact-text XPath either matched nothing at all, e.g. "Union Bank Of
    India" on the Debit Card tab, or silently failed to actually register
    the click, e.g. "Cash" on Pay at Bank Counter, which left the page's
    own Continue button permanently disabled).

    `scope`: a Page or a Locator to search within — BUG FIX (2026-09-02,
    round 2): a page-wide "mat-radio-button" search matched the same bank
    name's tile on a different, INACTIVE tab (every tab's radio group
    stays in the DOM, just marked inert, not removed — e.g. "ICICI Bank"
    is a tile on Net Banking, Debit Card, AND Payment Gateway), so the
    click landed on an inert/invisible radio and silently did nothing.
    Callers for tile clicks now pass the active tab panel Locator instead
    of the bare Page."""
    target_norm = _norm_bank_name(target_text)
    options = scope.locator(selector)
    await options.first.wait_for(state="visible", timeout=timeout)
    count = await options.count()
    for i in range(count):
        opt = options.nth(i)
        text_norm = _norm_bank_name(await opt.inner_text())
        if text_norm == target_norm:
            await opt.click()
            return
    raise RuntimeError(f"No element matching '{target_text}' found among {count} candidates ({selector!r})")


async def select_payment_mode(page, payment_mode: str, bank: str,
                              drawee_bank: str, step) -> None:
    """Pick the Payment Mode tab, then its mode-specific bank / sub-mode.

    Callers must click Continue afterwards — on the Income Tax flow that
    moves to the preview step, exactly as generate_challan() always did.
    """
    from automation.challan_generator import PAYMENT_MODES
    mode_info = PAYMENT_MODES[payment_mode]
    step(f"Selecting Payment Mode = {payment_mode}" + (f" / {bank}" if bank else "") + "...")
    await _click_visible_exact_text(page, "*", payment_mode, step, "CHALLAN")
    await asyncio.sleep(0.5)
    known_banks = mode_info.get("banks", [])
    # BUG FIX (2026-09-03): confirmed live — a row carrying a stray
    # `bank` value for a mode with no bank picklist at all (RTGS/NEFT's
    # own "banks" list is empty by design) fell through to the "Other
    # Bank" fallback and hunted for a #bankOther radio that doesn't exist,
    # hanging for the full 30s click timeout. A mode with no banks never
    # has anything to select here, regardless of what `bank` was passed in.
    if bank and known_banks:
        if bank in known_banks and bank != "Other Bank":
            # BUG FIX (2026-09-02): the portal's real tile text/markup doesn't
            # reliably match a naive exact string; and a page-wide radio search
            # could hit the same bank name on an INACTIVE tab. Scan the active
            # tab panel with tolerant matching instead.
            active_panel = page.locator(".mat-mdc-tab-body-active").last
            await _click_matching_option(active_panel, bank, selector="mat-radio-button")
        else:
            # Only a handful of banks get their own radio tile; every other
            # bank is reached via the "Other Bank" radio (stable id) plus
            # its nested searchable dropdown.
            step(f"'{bank}' not in the standard tile list — trying 'Other Bank'...")
            active_panel = page.locator(".mat-mdc-tab-body-active").last
            other_tile = active_panel.locator("#bankOther")
            await other_tile.wait_for(state="visible", timeout=10000)
            await other_tile.click()
            await asyncio.sleep(0.5)
            # Scope the trigger to the active panel so it can't match the
            # header's global language mat-select; the options overlay is
            # portaled to <body>, so that search stays page-wide.
            nested_select = active_panel.locator("mat-select, select").last
            await nested_select.wait_for(state="visible", timeout=10000)
            await nested_select.click()
            await _click_matching_option(page, bank)
        await asyncio.sleep(0.3)

    # BUG FIX (2026-09-02): Pay at Bank Counter has a SEPARATE mandatory
    # "Select Bank (authorised Banks only)" dropdown for every sub-mode
    # (Cash included). Reuse `drawee_bank` as its value — the only bank
    # name input the row carries for this mode.
    if payment_mode == "Pay at Bank Counter" and drawee_bank:
        step(f"Selecting Bank (authorised Banks only) = {drawee_bank}...")
        try:
            active_panel = page.locator(".mat-mdc-tab-body-active").last
            drawn_select = active_panel.locator("mat-select, select").last
            await drawn_select.click()
            await asyncio.sleep(0.3)
            await _click_matching_option(page, drawee_bank, timeout=8000)
        except Exception:
            try:
                drawn_input = page.locator(
                    "input[formcontrolname*='bank' i], input[placeholder*='bank' i]"
                ).first
                await drawn_input.click()
                await drawn_input.fill(drawee_bank)
            except Exception as e2:
                step(f"Could not set Drawn on Bank (best-effort, continuing): {e2}")
        await asyncio.sleep(0.3)


async def read_crn(page, step) -> tuple:
    """Return (crn, valid_till) from either confirmation-page variant."""
    try:
        crn_container = page.locator("div.labelCss", has_text="CRN").first
        await crn_container.wait_for(state="visible", timeout=8000)
        crn = (await crn_container.locator("div.valueCss").inner_text()).strip()
        valid_till = ""
        try:
            valid_container = page.locator("div.labelCss", has_text="Valid Till").first
            valid_till = (await valid_container.locator("div.valueCss").inner_text()).strip()
        except Exception:
            pass
        return crn, valid_till
    except Exception:
        # BUG FIX (2026-09-02): the online-payment "Pay Later" confirmation
        # page is a different Angular component (app-view-crn-details) with
        # no labelCss/valueCss pairs — the CRN is plain "CRN - <number>"
        # text in a page heading. Parse that instead.
        step("labelCss CRN block not found — trying online-mode 'CRN - <number>' heading...")
        heading = page.locator("text=/CRN\\s*-\\s*\\d+/").first
        await heading.wait_for(state="visible", timeout=10000)
        heading_text = await heading.inner_text()
        match = re.search(r"CRN\s*-\s*(\d+)", heading_text)
        if not match:
            raise RuntimeError(f"Could not parse CRN from heading text: {heading_text!r}")
        return match.group(1), ""


async def save_artifact(page, mode_info: dict, artifact_dir: str,
                        filename_base: str, step) -> str:
    """Download the Challan/Mandate PDF, or screenshot the confirmation page
    for modes that produce no downloadable document."""
    os.makedirs(artifact_dir, exist_ok=True)
    if mode_info["has_download"]:
        doc_label = "Challan Form" if mode_info["artifact"] == "challan_form" else "Mandate Form"
        step(f"Downloading {doc_label} PDF...")
        path = os.path.join(artifact_dir, filename_base + ".pdf")
        download_btn = page.locator("button", has_text=f"Download {doc_label}").first
        async with page.expect_download() as download_info:
            await download_btn.click()
        await (await download_info.value).save_as(path)
    else:
        # No downloadable document for this mode — the confirmation page
        # already fetched for CRN/Valid Till is itself the artifact worth
        # keeping, so screenshot it directly.
        step("No download for this mode — screenshotting confirmation page...")
        path = os.path.join(artifact_dir, filename_base + ".png")
        await page.screenshot(path=path, full_page=True)
    step(f"[Victory] Challan generated: {os.path.basename(path)}")
    return path
