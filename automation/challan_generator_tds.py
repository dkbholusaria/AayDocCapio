"""
automation/challan_generator_tds.py
===================================
F-4 — TDS/TCS challan generation (Challan 281, Income-tax Act 2025) for a
deductor TAN, via e-Pay Tax > New Payment > Pay TDS/TCS.

Confirmed live 2026-11-20 (see PlansofThisProject/F-4_tds_tcs_challan.md):
  1. navigate_to_epay_tax_act(page, log, "TY") — Act 2025.
  2. New Payment > Tax Year > "Pay TDS/TCS" tile's own Proceed.
  3. Select Deductee Type: Other than Company (0021) + Resident.
  4. Add Nature Of Payment Details: per-section code + Tax/Surcharge/Cess;
     Add; up to 20 codes; then common Interest / Late Fee 427 / Penalty /
     Others.
  5. Verify Tax Break Up Details (read-only) > Continue.
  6. Select Payment Mode — same five modes/banks as the Income Tax flow.
  7. Preview > Continue > CRN > Challan Form / Mandate Form PDF.

v1 scope: Other than Company + Resident only. Company / Non-Resident and
Act 1961 (old Challan 281) are deliberately unsupported.
"""
import asyncio
import os
import re

from automation.challan_fields import (
    TDS_AMOUNT_FIELDS, TDS_OTHER_AMOUNT_FIELDS,
)
from automation.challan_generator import (
    PAYMENT_MODES, DEFAULT_PAYMENT_MODE, bank_problem, drawee_bank_problem,
    cash_limit_exceeded,
)
from automation.challan_common import (
    select_payment_mode, read_crn, save_artifact,
)
from automation.downloader import update_browser_status, make_step_logger
from automation.downloader_challans import (
    navigate_to_epay_tax_act, _click_visible_exact_text,
)
from automation.diagnostics import capture_failure
from automation.tds_sections import section_by_code
from utils import migrate_challan_subfolder_names
from vault import identify_type


MINOR_HEAD = "TDS/TCS Payable by Taxpayer (200)"
MAX_SECTIONS = 20
CASH_LIMIT = 10000

DEDUCTEE_TYPES = {
    "other_than_company": {"label": "Other than Company Deductee(s)", "radio_value": "0021"},
    "company":            {"label": "Company Deductee(s)",            "radio_value": "0020"},
}
SUPPORTED_DEDUCTEE_TYPES = {"other_than_company"}

RESIDENCE = {
    "resident":     {"label": "Resident Deductee(s)",     "radio_value": "resident"},
    "non_resident": {"label": "Non-Resident Deductee(s)", "radio_value": "nonResident"},
}
SUPPORTED_RESIDENCE = {"resident"}


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def tds_row_total(row: dict) -> float:
    total = 0.0
    for sec in row.get("sections", []) or []:
        total += sum(_num(sec.get(k)) for k in TDS_AMOUNT_FIELDS)
    total += sum(_num(row.get(k)) for k in TDS_OTHER_AMOUNT_FIELDS)
    return total


def validate_tds_row(row: dict) -> str:
    """Return "" if the row is safe to submit, else a short human reason."""
    if identify_type(row.get("tan", "")) != "TAN":
        return "needs a valid 10-character TAN (e.g. ABCD12345E)"
    if row.get("deductee_type", "other_than_company") not in SUPPORTED_DEDUCTEE_TYPES:
        return "Company Deductee(s) is not supported yet — only Other than Company"
    if row.get("residence", "resident") not in SUPPORTED_RESIDENCE:
        return "Non-Resident Deductee(s) is not supported yet — only Resident"

    sections = row.get("sections") or []
    if not sections:
        return "needs at least one TDS section"
    if len(sections) > MAX_SECTIONS:
        return f"has {len(sections)} sections — the portal allows at most {MAX_SECTIONS}"
    for sec in sections:
        code = str(sec.get("section_code", "")).strip()
        if not section_by_code(code):
            return f"uses unknown section code '{code}'"
        for k in TDS_AMOUNT_FIELDS:
            if _num(sec.get(k)) < 0:
                return f"has a negative amount in section {code}"
    if tds_row_total(row) <= 0:
        return "total is zero — enter at least one amount"

    mode = row.get("payment_mode", "")
    if mode not in PAYMENT_MODES:
        return f"has unknown payment mode '{mode}'"
    problem = bank_problem(mode, row.get("bank", ""))
    if problem:
        return problem
    problem = drawee_bank_problem(mode, row.get("drawee_bank", ""))
    if problem:
        return problem
    if cash_limit_exceeded(mode, row.get("bank", ""), tds_row_total(row)):
        return (f"Pay at Bank Counter / Cash is capped at ₹{CASH_LIMIT:,} (RBI rule) — "
                f"total is ₹{tds_row_total(row):,.0f}. Use Cheque/Demand Draft instead.")
    return ""


async def _pick_tax_year(page, portal_year_label: str, step) -> None:
    year_select = page.locator("mat-select[formcontrolname='assessmentYear']").first
    await year_select.wait_for(state="visible", timeout=15000)
    await year_select.click()
    await asyncio.sleep(0.5)
    option = page.locator("mat-option").filter(has_text=portal_year_label).first
    await option.wait_for(state="visible", timeout=10000)
    await option.click()
    await asyncio.sleep(0.8)
    step(f"Tax Year selected: {portal_year_label}")


async def _open_tds_wizard(page, portal_year_label: str, step) -> None:
    await _click_visible_exact_text(page, "button", "New Payment", step, "TDS")
    await asyncio.sleep(2.0)
    await _pick_tax_year(page, portal_year_label, step)
    # Scope Proceed to the TDS tile: a page-wide search picks the hidden
    # #okBtnNav3 modal button first (confirmed live 2026-11-20).
    tile = page.locator("div.matcard").filter(has_text="Pay TDS/TCS").first
    await tile.wait_for(state="visible", timeout=15000)
    await tile.locator("button.proceed").first.click()
    await page.wait_for_load_state("domcontentloaded", timeout=30000)
    await asyncio.sleep(2.0)


async def _select_deductee_type(page, deductee_type: str, residence: str, step) -> None:
    dt = DEDUCTEE_TYPES[deductee_type]
    rs = RESIDENCE[residence]
    # Clicking the mat-radio-button host did not register live; the native
    # input must be checked directly (confirmed 2026-11-20).
    await page.locator(f"input[value='{dt['radio_value']}']").check(force=True)
    await asyncio.sleep(0.6)
    await page.locator(f"input[value='{rs['radio_value']}']").check(force=True)
    await asyncio.sleep(0.6)
    step(f"Deductee type: {dt['label']} / {rs['label']}")
    await _click_visible_exact_text(page, "button", "Continue", step, "TDS")
    await page.wait_for_load_state("domcontentloaded", timeout=30000)
    await asyncio.sleep(2.0)


async def _pick_section(page, code: str, step) -> str:
    select = page.locator("mat-select[formcontrolname='selectedSection']").first
    await select.click()
    await asyncio.sleep(0.8)
    options = page.locator("mat-option")
    await options.first.wait_for(state="visible", timeout=10000)
    count = await options.count()
    for i in range(count):
        text = (await options.nth(i).inner_text()).strip()
        if re.search(rf"-\s*{re.escape(str(code))}$", text):
            await options.nth(i).click()
            await asyncio.sleep(0.8)
            return text
    raise RuntimeError(f"Section code {code} is not offered by the portal's dropdown")


async def _add_section(page, sec: dict, step) -> None:
    code = str(sec.get("section_code", "")).strip()
    desc = await _pick_section(page, code, step)
    inputs = page.locator("input[formcontrolname='amount']")
    count = await inputs.count()
    if count < 3:
        raise RuntimeError(f"Expected 3 amount inputs on the section form, found {count}")
    for idx, key in enumerate(TDS_AMOUNT_FIELDS):
        value = _num(sec.get(key))
        await inputs.nth(idx).fill(str(int(value)) if float(value).is_integer() else str(value))
        await asyncio.sleep(0.2)

    before = await page.locator("table tr").count()
    add_btn = page.locator("//button[normalize-space(.)='Add']").first
    await add_btn.wait_for(state="visible", timeout=8000)
    await add_btn.click()
    for _ in range(20):
        await asyncio.sleep(0.4)
        if await page.locator("table tr").count() > before:
            step(f"Added section {code} — {desc[:60]}")
            return
    raise RuntimeError(f"Section {code} was picked but did not appear in the table")


async def _fill_other_payments(page, row: dict, step) -> None:
    for key in TDS_OTHER_AMOUNT_FIELDS:
        value = _num(row.get(key))
        box = page.locator(f"input[formcontrolname='{key}']").first
        await box.fill(str(int(value)) if float(value).is_integer() else str(value))
        await asyncio.sleep(0.15)
    step("Other payments filled")


async def generate_tds_challan(page, portal_year_label: str, row: dict,
                               output_dir: str, log_callback) -> dict:
    """Generate ONE TDS/TCS challan on an already logged-in TAN session.

    Returns a TDS_SUMMARY_COLUMNS-shaped dict. Never clicks Pay Now.
    """
    step = make_step_logger(log_callback, "TDS")
    mode_info = PAYMENT_MODES.get(row.get("payment_mode"), PAYMENT_MODES[DEFAULT_PAYMENT_MODE])
    total_amount = tds_row_total(row)
    tan = row.get("tan", "").strip().upper()

    problem = validate_tds_row(row)
    if problem:
        return {
            "tan": tan, "name": row.get("name", ""), "portal_year_label": portal_year_label,
            "sections": row.get("sections", []), "total_amount": total_amount,
            "payment_mode": row.get("payment_mode", ""), "bank": row.get("bank", ""),
            "drawee_bank": row.get("drawee_bank", ""), "crn": "", "valid_till": "",
            "status": "failed", "reason": f"Row {problem}", "artifact_path": "",
        }

    try:
        step(f"Generating TDS/TCS challan — TAN={tan}, TY={portal_year_label}, "
             f"{len(row['sections'])} section(s), total=₹{total_amount:,.0f}")

        year_tag = f"TY_{portal_year_label.replace('-', '_')}"
        migrate_challan_subfolder_names(output_dir, step)
        challan_dir = os.path.join(output_dir, "Tax Challans (Payable)")
        os.makedirs(challan_dir, exist_ok=True)

        await navigate_to_epay_tax_act(page, log_callback, "TY")
        await _open_tds_wizard(page, portal_year_label, step)
        await _select_deductee_type(page, row["deductee_type"], row["residence"], step)

        step("Step 2: adding section-wise payment details...")
        for sec in row["sections"]:
            await _add_section(page, sec, step)
        await _fill_other_payments(page, row, step)

        await _click_visible_exact_text(page, "button", "Continue", log_callback, "TDS")
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(2.0)

        step("Step 3: verifying tax break-up summary...")
        await _click_visible_exact_text(page, "button", "Continue", log_callback, "TDS")
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(2.0)

        step("Step 4: selecting payment mode...")
        await select_payment_mode(page, row["payment_mode"], row.get("bank", ""),
                                  row.get("drawee_bank", ""), step)
        await _click_visible_exact_text(page, "button", "Continue", log_callback, "TDS")
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(2.0)

        # Preview page. Same HARD STOP rule as F-64: Continue generates the
        # CRN for bank-counter / RTGS-NEFT modes; online modes only offer
        # Pay Later. Pay Now is never clicked.
        if mode_info["has_download"]:
            step("Preview: generating CRN...")
            await _click_visible_exact_text(page, "button", "Continue", log_callback, "TDS")
        else:
            step("Clicking Pay Later (never Pay Now)...")
            await _click_visible_exact_text(page, "button", "Pay Later", log_callback, "TDS")
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(2.0)

        crn, valid_till = await read_crn(page, step)
        filename_base = f"{tan}-TDS-Challan-{year_tag}-{crn}"
        output_path = await save_artifact(page, mode_info, challan_dir, filename_base, step)
        await update_browser_status(page, "TDS Challan Generated!")

        return {
            "tan": tan, "name": row.get("name", ""), "portal_year_label": portal_year_label,
            "sections": row["sections"], "total_amount": total_amount,
            "payment_mode": row["payment_mode"], "bank": row.get("bank", ""),
            "drawee_bank": row.get("drawee_bank", ""), "crn": crn,
            "valid_till": valid_till, "status": "generated", "reason": "",
            "artifact_path": output_path,
        }

    except Exception as e:
        err = str(e)
        step(f"[Error] Failed to generate TDS challan: {err}")
        await capture_failure(page, log_callback, "TDS_CHALLAN_failed")
        if "Timeout" in err or "timeout" in err:
            reason = "Timed out — ITD dashboard still loading (try again)"
        elif "net::" in err.lower():
            reason = "Network error — check internet connection"
        else:
            reason = err[:80] if len(err) <= 80 else err[:77] + "..."
        return {
            "tan": tan, "name": row.get("name", ""), "portal_year_label": portal_year_label,
            "sections": row.get("sections", []), "total_amount": total_amount,
            "payment_mode": row.get("payment_mode", ""), "bank": row.get("bank", ""),
            "drawee_bank": row.get("drawee_bank", ""), "crn": "", "valid_till": "",
            "status": "failed", "reason": reason, "artifact_path": "",
        }
