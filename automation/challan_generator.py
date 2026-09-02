"""
automation/challan_generator.py
=================================
F-64 — Generate tax payment challans (not download already-paid ones, see
downloader_challans.py for that) via the ITD e-Pay Tax "New Payment" wizard,
stopping before actual payment.

Confirmed portal flow (from live screenshots the user captured, see
PlansofThisProject/F-64_bulk_tax_challan_generation.md):
  1. navigate_to_epay_tax_act() (shared with downloader_challans.py) lands on
     the e-Pay Tax dashboard for the correct Act.
  2. "New Payment" (a "+" icon + text "New Payment" — the "+" is an image,
     not part of the button's text) > "Income Tax" tile > Proceed.
  3. Step 1 "Add Tax Applicable Details": Tax Year + Type of Payment (Minor
     Head) > Continue.
  4. Step 2 "Add Tax Break Up Details": (a) Tax ... (f) Others > Continue.
  5. Step 3a "Select Payment Mode": Pay at Bank Counter > Cheque > Continue.
  6. Step 3b "Preview And Make Payment": click "Pay Later" — HARD STOP,
     "Pay Now" is never clicked anywhere in this file. "Pay Later" still
     generates a real CRN and saves the challan under the portal's own
     "Generated Challans" tab, without touching net banking/OTP/any bank
     redirect.
  7. Generated Challans tab > locate the new row by CRN > Download > real
     Challan Form PDF (confirmed against a real sample the user provided,
     26090200112429_ChallanForm.pdf).

UNCONFIRMED live: every selector past the Act-selection step (already
proven in F-61) is a principled best-effort guess from the wizard's
screenshots, not yet verified against a live "New Payment" run — refine
here first if a step fails, same as downloader_challans.py went through
several rounds of live fixes before it was reliable.
"""
import asyncio
import os
import re

from playwright.async_api import Page

from automation.downloader import update_browser_status, make_step_logger
from automation.downloader_challans import (
    navigate_to_epay_tax_act,
    _first_visible,
    _click_visible_exact_text,
)
from automation.diagnostics import capture_failure
from automation.challan_fields import CHALLAN_AMOUNT_FIELDS


TAX_TYPES = {
    "advance":         {"label": "Advance Tax (100)",         "act_year_type": "TY"},
    # Confirmed live (2026-09-02): the portal's own dropdown option is
    # hyphenated "Self-Assessment Tax (300)", not "Self Assessment Tax".
    "self_assessment": {"label": "Self-Assessment Tax (300)", "act_year_type": "AY"},
}

# Per-mode metadata, confirmed live by the user exercising all four tabs on
# the real "Select Payment Mode" step directly (screenshots + real downloaded
# samples 26090200112429_ChallanForm.pdf / 26090200113931_MandateForm.pdf):
#   - Net Banking / Debit Card / Payment Gateway: no downloadable document
#     from Generated Challans afterward, only a "View Details" panel — every
#     mode has that, so it's the fallback artifact for these.
#   - Pay at Bank Counter: real "Challan Form" PDF, but its own sub-mode
#     (Cash/Cheque/Demand Draft) matters — Cash is capped at ₹10,000 total
#     (RBI rule); Cheque/DD have no cap.
#   - RTGS/NEFT: real "Mandate Form" PDF (a different document — beneficiary
#     bank/IFSC details for the remitting bank), no bank/sub-mode picklist
#     on this step.
# "banks" doubles as the sub-mode list for Pay at Bank Counter (Cash/Cheque/
# Demand Draft aren't literally banks, but they occupy the same UI slot and
# selection code path).
#
# "extended_banks": per the user's direction, the dialog shows ONE flat
# picklist per mode rather than a visible "Other Bank" tier — this code
# decides on its own, per bank name (see generate_challan()'s Step 3a),
# whether a given name is one of the primary on-screen tiles (clicked
# directly) or needs the "Other Bank" tile + its own nested search (any
# name not in "banks").
#
# Net Banking's full 32-bank authorized list, confirmed directly from the
# real portal's own "List of Banks" popup (Authorised Banks List — a live
# HTML capture dumped this verbatim, 2026-09-02), which supersedes an
# earlier guess sourced from a web-fetched help page summary that turned
# out to include one bank not actually on the real list ("Reserve Bank of
# India" — dropped) and one name spelled slightly differently ("Tamilnad
# Mercantile Bank Ltd", not "...Bank"). Exact casing kept as shown on the
# portal (e.g. "YES BANK") since the automation matches this text exactly.
# The 8 in "banks" below are the ones already confirmed as primary
# on-screen tiles from the live screenshot; the rest sit behind "Other
# Bank" on the real portal, hence "extended".
_NET_BANKING_EXTENDED = [
    "Bandhan Bank", "Bank of India", "Bank of Maharashtra", "Canara Bank",
    "Central Bank of India", "City Union Bank", "DCB Bank", "Dhanlaxmi Bank",
    "DBS Bank India Limited", "Federal Bank", "IDFC FIRST Bank",
    "Indian Bank", "Indian Overseas Bank", "IndusInd Bank",
    "Jammu & Kashmir Bank", "Karnataka Bank", "Karur Vysya Bank",
    "Punjab & Sind Bank", "RBL Bank", "South Indian Bank",
    "Tamilnad Mercantile Bank Ltd", "UCO Bank", "Union Bank of India",
    "YES BANK",
]
# Debit Card is NOT the same 33-bank list — the same ITD page states
# explicitly: "debit cards of Canara Bank, ICICI Bank, Indian Bank, State
# Bank of India, Punjab National Bank and Union Bank of India are being
# offered" — exactly these 6, confirmed, no broader extended list.
_DEBIT_CARD_EXTENDED = []

PAYMENT_MODES = {
    "Net Banking": {
        "banks": ["Axis Bank", "Bank Of Baroda", "HDFC Bank", "ICICI Bank", "IDBI Bank",
                  "Kotak Mahindra Bank", "Punjab National Bank", "State Bank Of India", "Other Bank"],
        "extended_banks": _NET_BANKING_EXTENDED,
        "has_download": False, "artifact": "view_details_screenshot",
    },
    "Debit Card": {
        "banks": ["Canara Bank", "ICICI Bank", "Indian Bank", "Punjab National Bank",
                  "State Bank Of India", "Union Bank Of India"],
        "extended_banks": _DEBIT_CARD_EXTENDED,
        "has_download": False, "artifact": "view_details_screenshot",
    },
    "Pay at Bank Counter": {
        "banks": ["Cash", "Cheque", "Demand Draft"],
        "extended_banks": [],
        "has_download": True, "artifact": "challan_form",
    },
    "RTGS/NEFT": {
        "banks": [],
        "extended_banks": [],
        "has_download": True, "artifact": "mandate_form",
    },
    "Payment Gateway including UPI and Credit Card": {
        "banks": [],
        "extended_banks": [],
        "has_download": False, "artifact": "view_details_screenshot",
    },
}
DEFAULT_PAYMENT_MODE = "Pay at Bank Counter"
DEFAULT_BANK = "Cheque"
CASH_LIMIT = 10000  # RBI rule: Pay at Bank Counter > Cash is capped at this total amount


def all_bank_options(payment_mode: str) -> list:
    """Flattened, de-duplicated bank/sub-mode list for one mode — primary
    on-screen tiles first, then the best-effort extended list — with the
    literal "Other Bank" tile excluded (it's an internal implementation
    detail now, not something the user picks directly; see PAYMENT_MODES'
    docstring above)."""
    info = PAYMENT_MODES.get(payment_mode, {})
    primary = [b for b in info.get("banks", []) if b != "Other Bank"]
    extended = info.get("extended_banks", [])
    seen = set()
    out = []
    for b in primary + extended:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def cash_limit_exceeded(payment_mode: str, bank: str, total_amount: float) -> bool:
    """Client-side mirror of the portal's own ₹10,000 Cash cap (confirmed by
    the user testing it live), so the dialog can flag a row before it ever
    reaches the portal, not just after a failed submission."""
    return payment_mode == "Pay at Bank Counter" and bank == "Cash" and total_amount > CASH_LIMIT


def resolve_tax_type(fy_value: str, ay_entries: list) -> tuple:
    """Looks up which of Advance Tax / Self-Assessment Tax applies to a
    Financial Year, using the app's own assessment_years.json entries
    (ay_entries — the same list app.py already loads via _load_ay_list())
    rather than computing a 31-March cutoff date independently. Confirmed
    directly from that file: "AY 2026-27" and "TY 2026-27" are NOT the same
    period (AY 2026-27 -> FY 2025-26, already closed; TY 2026-27 -> FY
    2026-27, still open) — the matching number is a coincidence of adjacent
    labels, not the same year, so this must look up the FY, not the label.

    Returns (tax_type, portal_year_label). Raises ValueError if the FY isn't
    in the year list yet, or if it somehow has both a TY and an AY entry
    (ambiguous — should not happen with a well-formed year list)."""
    ty_label = None
    ay_label = None
    for entry in ay_entries:
        y = entry.get("year", {})
        if y.get("FY") != fy_value:
            continue
        if y.get("TY"):
            ty_label = y["TY"]
        if y.get("AY"):
            ay_label = y["AY"]

    if ty_label and ay_label:
        raise ValueError(
            f"FY {fy_value} has both a Tax Year and an Assessment Year entry in the year list — "
            "ambiguous, please check Manage Years."
        )
    if ty_label:
        return "advance", ty_label
    if ay_label:
        return "self_assessment", ay_label
    raise ValueError(f"FY {fy_value} is not in the year list yet — add it via Manage Years first.")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (text or "").strip()).strip("_") or "Payment"


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


async def _click_matching_option(page: Page, target_text: str, timeout: int = 10000):
    """Find and click the open dropdown option whose text matches target_text
    once both are loosely normalized (see _norm_bank_name) — tolerant of the
    casing/wording drift confirmed live between this app's bank-name lists
    and the portal's actual option text."""
    target_norm = _norm_bank_name(target_text)
    options = page.locator("mat-option, [role='option']")
    await options.first.wait_for(state="visible", timeout=timeout)
    count = await options.count()
    for i in range(count):
        opt = options.nth(i)
        text_norm = _norm_bank_name(await opt.inner_text())
        if text_norm == target_norm:
            await opt.click()
            return
    raise RuntimeError(f"No dropdown option matching '{target_text}' found among {count} options")


async def _check_type_of_payment_available(page: Page, tax_type: str, step) -> bool:
    """Defensive safety net for resolve_tax_type()'s primary date/year-list
    based decision: confirms the computed Type-of-Payment option is actually
    present and enabled in the portal's own Step 1 dropdown before selecting
    it. Never falls back to the other type — a mismatch here means the
    caller should stop, not guess."""
    label = TAX_TYPES[tax_type]["label"]
    try:
        option = page.locator(f"//*[normalize-space(.)='{label}']").first
        await option.wait_for(state="visible", timeout=8000)
        return await option.is_enabled()
    except Exception as e:
        step(f"Type of Payment '{label}' not found/enabled: {e}")
        return False


async def generate_challan(
    page: Page,
    fy_value: str,
    portal_year_label: str,
    tax_type: str,
    amounts: dict,
    payment_mode: str,
    bank: str,
    drawee_bank: str,
    output_dir: str,
    log_callback,
    pan: str = "",
    dob: str = "",
) -> dict:
    """Generates ONE challan for one already-logged-in client, on a page
    already navigated to the correct e-Pay Tax Act dashboard via
    navigate_to_epay_tax_act(page, log, TAX_TYPES[tax_type]["act_year_type"]).

    `amounts`: {"tax", "surcharge", "cess", "interest", "penalty", "others"}
    — per the user's rule, a row with only a lump sum should have put it all
    in "tax" before calling this (see ui/dialogs.py's GenerateChallansDialog);
    this function does not redistribute amounts itself.

    `payment_mode`: one of PAYMENT_MODES' keys (e.g. "Net Banking", "Pay at
    Bank Counter"). `bank`: the bank tile for Net Banking/Debit Card, or the
    sub-mode (Cash/Cheque/Demand Draft) for Pay at Bank Counter, or "" for
    RTGS/NEFT and Payment Gateway (no picklist on this step). `drawee_bank`:
    the bank the cheque/DD is drawn on — confirmed against a real sample PDF
    ("Drawn on Bank: Kotak Mahindra Bank") — only meaningful (and only ever
    filled) when payment_mode is "Pay at Bank Counter" and bank is "Cheque"
    or "Demand Draft"; ignored otherwise.

    Returns {"fy_value", "portal_year_label", "tax_type", "crn", "total_amount",
    "valid_till", "payment_mode", "bank", "drawee_bank",
    "status": "generated"|"failed"|"unavailable", "reason", "artifact_path"}."""
    step = make_step_logger(log_callback, "CHALLAN")
    mode_info = PAYMENT_MODES.get(payment_mode, PAYMENT_MODES[DEFAULT_PAYMENT_MODE])
    total_amount = sum(float(amounts.get(f, 0) or 0) for f in CHALLAN_AMOUNT_FIELDS)

    if cash_limit_exceeded(payment_mode, bank, total_amount):
        return {
            "fy_value": fy_value, "portal_year_label": portal_year_label, "tax_type": tax_type,
            "crn": "", "total_amount": total_amount, "valid_till": "",
            "payment_mode": payment_mode, "bank": bank, "drawee_bank": drawee_bank, "status": "failed",
            "reason": f"Pay at Bank Counter / Cash is capped at ₹{CASH_LIMIT:,} (RBI rule) — "
                      f"total is ₹{total_amount:,.0f}. Use Cheque/Demand Draft instead.",
            "artifact_path": "",
        }

    try:
        step(f"Generating challan — FY={fy_value}, portal_year={portal_year_label}, "
             f"type={tax_type}, mode={payment_mode}/{bank}, total=₹{total_amount:,.0f}")

        challan_dir = os.path.join(output_dir, "Tax Challans (Generated)")
        os.makedirs(challan_dir, exist_ok=True)

        step("Clicking + New Payment...")
        # Confirmed live from a real failure capture: the "+" is a leading
        # <img> icon, not text — the button's actual normalized text
        # content is just "New Payment", so an exact match on "+ New
        # Payment" never matched anything.
        await _click_visible_exact_text(page, "button", "New Payment", log_callback, "CHALLAN")
        await asyncio.sleep(1.0)

        step("Clicking Income Tax tile > Proceed...")
        income_tax_tile = page.locator("//*[normalize-space(.)='Income Tax']").first
        await income_tax_tile.wait_for(state="visible", timeout=15000)
        # UNCONFIRMED: the tile's own "Proceed" button vs a page-level one —
        # scoped to the tile's container, falling back to the first visible
        # "Proceed" match if the container scoping doesn't hold live.
        try:
            proceed_btn = income_tax_tile.locator(
                "xpath=ancestor::*[contains(@class,'card') or contains(@class,'tile')][1]//button[normalize-space(.)='Proceed']"
            ).first
            await proceed_btn.wait_for(state="visible", timeout=5000)
            await proceed_btn.click()
        except Exception:
            await _click_visible_exact_text(page, "button", "Proceed", log_callback, "CHALLAN")
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(1.0)

        step(f"Step 1: selecting Tax Year {portal_year_label} and {TAX_TYPES[tax_type]['label']}...")
        year_select_all = page.locator(
            "mat-select[formcontrolname='assessmentYear'], mat-select[formcontrolname='taxYear']"
        )
        year_select = await _first_visible(year_select_all, timeout_ms=10000)
        if year_select is None:
            raise RuntimeError("Tax Year selector not found on Step 1")
        await year_select.click()
        year_option = page.locator(f"mat-option:has-text('{portal_year_label}')").first
        await year_option.wait_for(state="visible", timeout=10000)
        await year_option.click()
        await asyncio.sleep(0.3)

        type_select_all = page.locator("mat-select[formcontrolname='minorHead'], mat-select[formcontrolname='typeOfPayment']")
        type_select = await _first_visible(type_select_all, timeout_ms=10000)
        if type_select is None:
            raise RuntimeError("Type of Payment selector not found on Step 1")
        await type_select.click()

        if not await _check_type_of_payment_available(page, tax_type, step):
            await capture_failure(page, log_callback, "CHALLAN_GEN_type_unavailable")
            return {
                "fy_value": fy_value, "portal_year_label": portal_year_label, "tax_type": tax_type,
                "crn": "", "total_amount": total_amount, "valid_till": "",
                "payment_mode": payment_mode, "bank": bank, "drawee_bank": drawee_bank,
                "status": "unavailable",
                "reason": f"{TAX_TYPES[tax_type]['label']} not available for {portal_year_label} on the portal yet",
                "artifact_path": "",
            }

        type_option = page.locator(f"mat-option:has-text('{TAX_TYPES[tax_type]['label']}')").first
        await type_option.click()
        await asyncio.sleep(0.3)

        await _click_visible_exact_text(page, "button", "Continue", log_callback, "CHALLAN")
        await page.wait_for_load_state("domcontentloaded", timeout=20000)
        await asyncio.sleep(1.0)

        step("Step 2: filling Tax Break Up Details...")
        # Confirmed live (2026-09-02 diagnostic capture): the portal's actual
        # formcontrolname values are "<field>Amt", not the bare field name
        # ("taxAmt", "surchargeAmt", ... — Tax also carries id="basicTax").
        field_selectors = {
            "tax": "input[formcontrolname='taxAmt']",
            "surcharge": "input[formcontrolname='surchargeAmt']",
            "cess": "input[formcontrolname='cessAmt']",
            "interest": "input[formcontrolname='interestAmt']",
            "penalty": "input[formcontrolname='penaltyAmt']",
            "others": "input[formcontrolname='othersAmt']",
        }
        for field, selector in field_selectors.items():
            value = amounts.get(field, 0) or 0
            if not value:
                continue
            box = page.locator(selector).first
            await box.click()
            await box.fill(str(int(value) if float(value).is_integer() else value))
        await asyncio.sleep(0.3)

        await _click_visible_exact_text(page, "button", "Continue", log_callback, "CHALLAN")
        await page.wait_for_load_state("domcontentloaded", timeout=20000)
        await asyncio.sleep(1.0)

        step(f"Step 3a: selecting Payment Mode = {payment_mode}" + (f" / {bank}" if bank else "") + "...")
        await _click_visible_exact_text(page, "*", payment_mode, log_callback, "CHALLAN")
        await asyncio.sleep(0.5)
        if bank:
            known_banks = mode_info.get("banks", [])
            if bank in known_banks and bank != "Other Bank":
                bank_option = page.locator(f"//*[normalize-space(.)='{bank}']").first
                await bank_option.wait_for(state="visible", timeout=10000)
                await bank_option.click()
            else:
                # Confirmed live (2026-09-02): only a handful of banks get
                # their own radio tile (Axis, Bank of Baroda, HDFC, ICICI,
                # IDBI, Kotak Mahindra, Punjab National, SBI) — every other
                # bank is reached via the "Other Bank" radio, which reveals
                # a nested dropdown to pick the actual name from.
                step(f"'{bank}' not in the standard tile list — trying 'Other Bank'...")
                # BUG FIX (2026-09-02): the text-based XPath below matched
                # the wrapping <div class="margin24"> that contains ONLY
                # this radio button (so its aggregate text was also exactly
                # "Other Bank", and being an ancestor it sorts first in
                # document order) instead of the radio control itself —
                # confirmed live by a diagnostic screenshot showing "Other
                # Bank" still unchecked after the click. The portal gives
                # this radio a stable id="bankOther"; use that directly.
                other_tile = page.locator("#bankOther")
                await other_tile.wait_for(state="visible", timeout=10000)
                await other_tile.click()
                await asyncio.sleep(0.5)
                # BUG FIX (2026-09-02): page.locator("mat-select, select").last
                # matched the header's global language mat-select (always
                # present, later in DOM than the tab content in some layouts)
                # instead of the nested bank dropdown that just appeared,
                # confirmed live by a diagnostic screenshot showing the
                # English/Hindi language panel open instead of a bank list.
                # Scope the search to the active tab panel only.
                # The trigger lives inside the active tab panel — scope to
                # it so it can't match the header's language select. Its
                # dropdown options, once opened, render in a CDK overlay
                # portaled to <body> (not nested under the panel), so that
                # search stays page-wide — but by then only this select's
                # overlay is open, so there's no ambiguity to worry about.
                active_panel = page.locator(".mat-mdc-tab-body-active").last
                nested_select = active_panel.locator("mat-select, select").last
                await nested_select.wait_for(state="visible", timeout=10000)
                await nested_select.click()
                # BUG FIX (2026-09-02): an exact-text XPath match failed on
                # "Central Bank Of India" — the portal's actual option text
                # differs from our _NET_BANKING_EXTENDED entries in casing
                # ("Of" vs "of") and wording ("Limited" suffixes, "&" vs
                # "And") for several banks. Use tolerant matching instead.
                await _click_matching_option(page, bank)
            await asyncio.sleep(0.3)

        # Confirmed against a real sample PDF: Pay at Bank Counter's Cheque/
        # Demand Draft sub-modes carry their own "Drawn on Bank" field
        # (which bank the cheque/DD is drawn on) — Cash has no such field.
        # UNCONFIRMED live whether it's a dropdown or a free-text box; try
        # a dropdown first, fall back to typing into a text input.
        if payment_mode == "Pay at Bank Counter" and bank in ("Cheque", "Demand Draft") and drawee_bank:
            step(f"Selecting Drawn on Bank = {drawee_bank}...")
            try:
                # Same fix as the "Other Bank" dropdown above: scope the
                # trigger search to the active tab panel so it can't match
                # the header's global language mat-select.
                active_panel = page.locator(".mat-mdc-tab-body-active").last
                drawn_select = active_panel.locator("mat-select, select").last
                await drawn_select.click()
                await asyncio.sleep(0.3)
                # Same tolerant-matching fix as the "Other Bank" dropdown above.
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

        await _click_visible_exact_text(page, "button", "Continue", log_callback, "CHALLAN")
        await page.wait_for_load_state("domcontentloaded", timeout=20000)
        await asyncio.sleep(1.0)

        # Confirmed live (2026-09-02 diagnostic capture): "Pay Later" only
        # exists for modes with an actual online-payment choice to defer.
        # Pay at Bank Counter / RTGS-NEFT skip straight to a "Preview And
        # Download Challan Form" sub-step whose footer is just Back/Continue
        # — clicking it generates the CRN directly, no Pay Now/Pay Later
        # choice ever appears. HARD STOP: "Pay Now" is never clicked here.
        if mode_info["has_download"]:
            step("Step 3b: clicking Continue on Preview And Download Challan Form...")
            await _click_visible_exact_text(page, "button", "Continue", log_callback, "CHALLAN")
        else:
            step("Step 3b: clicking Pay Later (never Pay Now)...")
            await _click_visible_exact_text(page, "button", "Pay Later", log_callback, "CHALLAN")
        await page.wait_for_load_state("domcontentloaded", timeout=20000)
        await asyncio.sleep(1.5)

        prefix = f"{pan}-" if pan else ""

        # Confirmed live (2026-09-02) for Pay at Bank Counter: clicking
        # Continue/Pay Later above lands directly on a confirmation page
        # ("Visit Bank To Make Payment" for bank-counter modes) that already
        # shows CRN/Valid Till itself — no visit to the Generated Challans
        # tab is needed to read them. The online-payment modes (Net
        # Banking/Debit Card/Payment Gateway) use the same completion-step
        # component after "Pay Later", so this is assumed to hold there too
        # — UNCONFIRMED LIVE, no online-mode run has exercised this branch
        # yet.
        step("Fetching CRN from confirmation page...")
        crn = ""
        valid_till = ""
        try:
            crn_container = page.locator("div.labelCss", has_text="CRN").first
            await crn_container.wait_for(state="visible", timeout=8000)
            crn = (await crn_container.locator("div.valueCss").inner_text()).strip()
            try:
                valid_container = page.locator("div.labelCss", has_text="Valid Till").first
                valid_till = (await valid_container.locator("div.valueCss").inner_text()).strip()
            except Exception:
                pass
        except Exception:
            # BUG FIX (2026-09-02): confirmed live — the online-payment
            # (Net Banking/Debit Card/Payment Gateway) "Pay Later"
            # confirmation page is a DIFFERENT Angular component
            # (app-view-crn-details) than Pay at Bank Counter's, not the
            # same one as originally assumed. It has no labelCss/valueCss
            # pairs and no "Valid Till" field at all — the CRN instead
            # appears as plain text "CRN - <number>" in a page heading
            # (class "subHeading"). Fall back to parsing that.
            step("labelCss CRN block not found — trying online-mode 'CRN - <number>' heading...")
            heading = page.locator("text=/CRN\\s*-\\s*\\d+/").first
            await heading.wait_for(state="visible", timeout=10000)
            heading_text = await heading.inner_text()
            match = re.search(r"CRN\s*-\s*(\d+)", heading_text)
            if not match:
                raise RuntimeError(f"Could not parse CRN from heading text: {heading_text!r}")
            crn = match.group(1)

        if mode_info["has_download"]:
            doc_label = "Challan Form" if mode_info["artifact"] == "challan_form" else "Mandate Form"
            step(f"Downloading {doc_label} PDF...")
            filename = f"{prefix}Challan-{fy_value.replace('-', '_')}-{tax_type}-{crn}.pdf"
            output_path = os.path.join(challan_dir, filename)
            download_btn = page.locator("button", has_text=f"Download {doc_label}").first
            async with page.expect_download() as download_info:
                await download_btn.click()
            await (await download_info.value).save_as(output_path)
            step(f"[Victory] Challan generated: {os.path.basename(output_path)} (CRN {crn})")
        else:
            # No downloadable document for this mode (confirmed live by the
            # user for Net Banking/Debit Card/Payment Gateway) — the
            # confirmation page already fetched above for CRN/Valid Till is
            # itself the artifact worth keeping, so screenshot it directly
            # rather than navigating away to Generated Challans + View
            # Details.
            step("No download for this mode — screenshotting confirmation page...")
            filename = f"{prefix}Challan-{fy_value.replace('-', '_')}-{tax_type}-{crn}.png"
            output_path = os.path.join(challan_dir, filename)
            await page.screenshot(path=output_path, full_page=True)
            step(f"[Victory] Challan generated: {os.path.basename(output_path)} (CRN {crn})")

        await update_browser_status(page, "Challan Generated!")
        return {
            "fy_value": fy_value, "portal_year_label": portal_year_label, "tax_type": tax_type,
            "crn": crn, "total_amount": total_amount, "valid_till": valid_till,
            "payment_mode": payment_mode, "bank": bank, "drawee_bank": drawee_bank,
            "status": "generated", "reason": "", "artifact_path": output_path,
        }

    except Exception as e:
        err = str(e)
        step(f"[Error] Failed to generate challan: {err}")
        await capture_failure(page, log_callback, "CHALLAN_GEN_failed")
        if "Timeout" in err or "timeout" in err:
            reason = "Timed out — ITD dashboard still loading (try again)"
        elif "net::" in err.lower():
            reason = "Network error — check internet connection"
        elif "Target page" in err or "browser has been closed" in err:
            reason = "Browser closed unexpectedly"
        else:
            reason = err[:80] if len(err) <= 80 else err[:77] + "..."
        return {
            "fy_value": fy_value, "portal_year_label": portal_year_label, "tax_type": tax_type,
            "crn": "", "total_amount": total_amount, "valid_till": "",
            "payment_mode": payment_mode, "bank": bank, "drawee_bank": drawee_bank,
            "status": "failed", "reason": reason, "artifact_path": "",
        }
