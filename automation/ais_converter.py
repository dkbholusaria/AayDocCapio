"""
AIS JSON → Excel converter.

Public API:
    convert_ais_json(json_path, log_callback=None, pan=None, dob=None) -> str

Produces a structured xlsx workbook alongside the source JSON file.
Sheet layout follows the flat-table pattern from as26_converter.py:
  - One header row per sheet
  - Parent fields (Info Code, Description, Source) repeated on every data row
  - Subtotals after each element group, grand total at end
  - Numeric columns right-aligned; amounts in Indian comma format
"""

import os
import tempfile
from datetime import datetime

from automation.ais_json_decryptor import decrypt_ais_json, ais_derive_fy


# ── Classify SFT elements into output sheets ───────────────────────────────────

_SALES_L1SRC     = "AIS_SEC_DEP_MF"
_PURCHASE_L1SRC  = "AIS_SEC_DEP_MF_HLD_PUR_DIV"

# Fixed superset for Capital Market Sales (18-col SFT-18 is the widest; SFT-17 is 16)
# Column names are matched by name from each element's l1.columnLabel
_SALES_SUPERSET = [
    "TSN",
    "AMC Name (Code)",                    # SFT-18 only
    "Date of Sale/Transfer",
    "Security Class",
    "Security Name (Security Code)",
    "Debit Type",
    "Credit Type",
    "Asset Type",
    "Quantity",
    "Sale Price Per unit",
    "Sales Consideration",
    "STT",                                # SFT-18 only
    "Cost of Acquisition",
    "Unit FMV",
    "Fair Market Value",
    "Indexed Cost of Acquisition",
    "Status",
]

_PURCHASES_SUPERSET = [
    "TSN",
    "Quarter",
    "Client ID",
    "AMC Name (Code)",     # SFT-18(Pur) only; blank for SFT-17(Pur)
    "Holder Flag",
    "Purchase Amount",
    "Sales Amount",
    "Status",
]


# ── Utility helpers ────────────────────────────────────────────────────────────

def _split_security_name(raw: str) -> tuple[str, str]:
    """
    'VODAFONE IDEA LIMITED EQ(INE669E01016)' → ('INE669E01016', 'VODAFONE IDEA LIMITED EQ')
    Returns (isin, name). If no parenthetical, returns ('', raw).
    """
    raw = (raw or "").strip()
    if raw.endswith(")") and "(" in raw:
        paren = raw.rfind("(")
        isin = raw[paren + 1:-1].strip()
        name = raw[:paren].strip()
        return isin, name
    return "", raw


def _parse_amount(s: str) -> float | None:
    """'3,10,000.00' → 3100000.0; empty/None → None."""
    if not s:
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def _get_l2(elem: dict) -> dict:
    """Return l2 summary fields as a dict. Empty dict if no l2 data."""
    l2 = elem.get("l2") or {}
    rows = l2.get("columnData") or []
    if not rows:
        return {}
    r = rows[0]
    # l2 row order: category, info_code, description, source, count, amount, ...
    return {
        "category":    r[0] if len(r) > 0 else "",
        "info_code":   r[1] if len(r) > 1 else "",
        "description": r[2] if len(r) > 2 else "",
        "source":      r[3] if len(r) > 3 else "",
        "count":       r[4] if len(r) > 4 else "",
        "amount":      r[5] if len(r) > 5 else "",
    }


def _get_l1(elem: dict) -> tuple[list, list]:
    """Return (col_names, rows). Rows are trimmed to len(col_names)."""
    l1 = elem.get("l1")
    if not l1:
        return [], []
    labels = l1.get("columnLabel") or []
    col_names = [c.get("name", "") if isinstance(c, dict) else str(c) for c in labels]
    rows = l1.get("columnData") or []
    return col_names, [row[:len(col_names)] for row in rows]


def _infer_info_code(elem: dict) -> str:
    """Return l2 info_code, with narrow l1-label fallbacks for empty l2 SFT rows."""
    l2 = _get_l2(elem)
    code = l2.get("info_code", "")
    if code:
        return code
    for key in ("info_code", "infoCode", "code"):
        code = elem.get(key, "")
        if code:
            return str(code)

    l1_cols, _ = _get_l1(elem)
    col_set = set(l1_cols)
    if {"Total Purchase Amount", "Total Sales Value"}.issubset(col_set):
        return "SFT-18(Pur)"
    if {"Market Purchase", "Market Sales"}.issubset(col_set):
        return "SFT-17(Pur)"
    return ""


def _active_rows(col_names: list, rows: list) -> list:
    """Filter out rows where the Status column value is 'Inactive'."""
    try:
        idx = col_names.index("Status")
    except ValueError:
        return rows
    return [r for r in rows if (r[idx] if idx < len(r) else "") != "Inactive"]


def _build_dynamic_superset(elements: list) -> list:
    """Return ordered union of l1 column names from a list of elements."""
    seen: dict[str, int] = {}
    for elem in elements:
        l1 = elem.get("l1") or {}
        for c in (l1.get("columnLabel") or []):
            name = c.get("name", "") if isinstance(c, dict) else str(c)
            if name not in seen:
                seen[name] = len(seen)
    return list(seen.keys())


def _map_to_superset(row_vals: list, col_names: list, superset: list,
                     rename: dict | None = None) -> list:
    """Map a data row into superset column order (blanks for missing cols)."""
    col_map = {name: i for i, name in enumerate(superset)}
    out = [""] * len(superset)
    for val, name in zip(row_vals, col_names):
        effective = (rename or {}).get(name, name)
        idx = col_map.get(effective)
        if idx is not None:
            out[idx] = val
    return out


# ── safe move (same pattern as as26_converter.py) ─────────────────────────────

def _safe_move(tmp_path: str, xlsx_path: str) -> str:
    import shutil
    try:
        shutil.move(tmp_path, xlsx_path)
        return xlsx_path
    except PermissionError:
        base, ext = os.path.splitext(xlsx_path)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        alt = f"{base}_{ts}{ext}"
        shutil.move(tmp_path, alt)
        return alt


# ── Main xlsx writer ───────────────────────────────────────────────────────────

def _write_ais_xlsx(data: dict, xlsx_path: str, pan: str, fy: str,
                    download_date: str, assessee_name: str,
                    log_callback=None) -> str:
    import xlsxwriter

    def _log(msg):
        if log_callback:
            log_callback(msg)

    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".xlsx", dir=os.path.dirname(xlsx_path) or ".")
    os.close(tmp_fd)

    wb = xlsxwriter.Workbook(tmp_path, {
        "strings_to_numbers": False,
        "strings_to_formulas": True,
        "constant_memory": False,
    })

    # ── Colour constants ───────────────────────────────────────────────────
    # AIS uses Navy + Teal to differentiate from 26AS (which uses Navy + Dark Green)
    NAVY   = "#0A1628"
    GREEN  = "#0E6674"   # teal (headers, section rows)
    SUBTTL = "#d0eef2"   # light teal (subtotal rows)
    WHITE  = "#ffffff"
    GREY   = "#94A3B8"
    LABEL  = "#e8f5f7"   # very light teal (label cells)
    GREEN_NUM = "#7fffef" # teal highlight for numbers on navy grand total
    GREEN_TXT = "#0a2d33" # dark teal text on light teal backgrounds

    def _fmt(bold=False, size=10, color="#000000", italic=False,
             bg=None, align="left", valign="vcenter", wrap=False,
             num_fmt=None, border=1, border_color="#D0D0D0", top_color=None,
             underline=False):
        d = {
            "font_name": "Calibri", "font_size": size,
            "bold": bold, "italic": italic, "underline": underline,
            "font_color": color,
            "align": align, "valign": valign, "text_wrap": wrap,
            "left": border, "right": border, "top": border, "bottom": border,
            "left_color": border_color, "right_color": border_color,
            "top_color": top_color or border_color, "bottom_color": border_color,
        }
        if bg:     d["bg_color"] = bg
        if num_fmt: d["num_format"] = num_fmt
        return wb.add_format(d)

    F_DEFAULT    = _fmt()
    F_NUM        = _fmt(align="right", num_fmt='#,##0.00;(#,##0.00);"-"')
    F_QTY        = _fmt(align="right", num_fmt='#,##0.00')
    F_HDR        = _fmt(bold=True, color=WHITE, bg=GREEN, align="center", wrap=True)
    F_SUBTOT_LBL = _fmt(bold=True, color=GREEN_TXT, bg=SUBTTL, align="right",
                        top_color=GREEN)
    F_SUBTOT_NUM = _fmt(bold=True, color=GREEN_TXT, bg=SUBTTL, align="right",
                        num_fmt='#,##0.00;(#,##0.00);"-"', top_color=GREEN)
    F_SUBTOT_QTY = _fmt(bold=True, color=GREEN_TXT, bg=SUBTTL, align="right",
                        num_fmt='#,##0.00', top_color=GREEN)
    F_GRAND_LBL  = _fmt(bold=True, color=WHITE, bg=NAVY, align="right")
    F_GRAND_NUM  = _fmt(bold=True, color=GREEN_NUM, bg=NAVY, align="right",
                        num_fmt='#,##0.00;(#,##0.00);"-"')
    F_GRAND_QTY  = _fmt(bold=True, color=GREEN_NUM, bg=NAVY, align="right",
                        num_fmt='#,##0.00')
    F_BRAND_L    = _fmt(bold=True, size=10, color=WHITE, bg=NAVY, align="left")
    F_BRAND_R    = _fmt(size=8, color=GREY, bg=NAVY, align="right")
    F_TITLE      = _fmt(bold=True, size=13, color=WHITE, bg=NAVY, align="center")
    F_SUBTITLE   = _fmt(size=8, color=GREY, bg=NAVY, align="center", wrap=True)
    F_LABEL      = _fmt(bold=True, bg=LABEL)
    F_VALUE      = _fmt()
    F_SECTION    = _fmt(bold=True, color=WHITE, bg=GREEN)
    F_NOTES      = _fmt(bg="#fffde7", color="#6b4f00", wrap=True)
    F_LINK       = _fmt(color="#0563C1", underline=True)

    report_ts = datetime.now().strftime("%d-%b-%Y %H:%M")

    def _brand_row(ws, ncols):
        left_text = f"AIS — {assessee_name} — {pan} — FY {fy}"
        right_text = f"AayDoc Capio™  ·  {report_ts}  ·  © 2026  ·  CA. Deepak Bhholusaria"
        split = min(3, ncols - 2)
        ws.merge_range(0, 0, 0, split, left_text, F_BRAND_L)
        if split + 1 <= ncols - 1:
            ws.merge_range(0, split + 1, 0, ncols - 1, right_text, F_BRAND_R)
        ws.set_row(0, 16)

    _DISPLAY_RENAME = {"TSN": "TransID"}

    def _hdr_row(ws, cols, row=1):
        for c, h in enumerate(cols):
            ws.write(row, c, _DISPLAY_RENAME.get(h, h), F_HDR)
        ws.set_row(row, 28)  # Set height to 28 to support text wrapped headers
        ws.autofilter(row, 0, row, len(cols) - 1)

    def _autofit(ws, widths):
        for ci, w in enumerate(widths):
            ws.set_column(ci, ci, min(max(w + 2, 8), 60))

    # Shared: write all data rows for one element group (flat-table style)
    # Returns (first_data_row, last_data_row, {col_idx: subtotal})
    def _write_group(ws, row_start, prefix, l1_cols, l1_rows, superset, rename,
                     num_col_names, col_widths):
        """
        Write l1 rows for one element group into the worksheet.
        prefix : list of values for the leading columns (Info Code, Description, Source)
        superset: column names list for the data portion
        num_col_names: set of column names that should be written as numbers
        """
        n_prefix = len(prefix)
        totals = {}
        for vals in l1_rows:
            mapped = _map_to_superset(vals, l1_cols, superset, rename)
            full_row = prefix + mapped
            for ci, v in enumerate(full_row):
                if ci < n_prefix:
                    ws.write(row_start, ci, v, F_DEFAULT)
                    col_widths[ci] = max(col_widths.get(ci, 0), len(str(v)))
                else:
                    sup_idx = ci - n_prefix
                    col_name = superset[sup_idx] if sup_idx < len(superset) else ""
                    is_num = col_name in num_col_names
                    amt = _parse_amount(str(v)) if is_num else None
                    if amt is not None:
                        is_qty = any(q in col_name.lower() for q in ["quantity", "qty", "count"])
                        ws.write_number(row_start, ci, amt, F_QTY if is_qty else F_NUM)
                        totals[ci] = totals.get(ci, 0) + amt
                    else:
                        ws.write(row_start, ci, str(v) if v is not None else "", F_DEFAULT)
                    col_widths[ci] = max(col_widths.get(ci, 0), len(str(v)))
            row_start += 1
        return row_start, totals

    def _subtotal_row(ws, row, ncols, label, totals, col_widths, cols=None):
        """Write a subtotal row after a group."""
        ws.write(row, 0, label, F_SUBTOT_LBL)
        for ci in range(1, ncols):
            if ci in totals:
                col_name = cols[ci] if cols and ci < len(cols) else ""
                is_qty = any(q in col_name.lower() for q in ["quantity", "qty", "count"])
                ws.write_number(row, ci, totals[ci], F_SUBTOT_QTY if is_qty else F_SUBTOT_NUM)
            else:
                ws.write_blank(row, ci, None, F_SUBTOT_LBL)
        ws.set_row(row, 14)
        col_widths[0] = max(col_widths.get(0, 0), len(label))

    def _grand_total_row(ws, row, ncols, grand_totals, col_widths, cols=None):
        ws.write(row, 0, "Grand Total", F_GRAND_LBL)
        for ci in range(1, ncols):
            if ci in grand_totals:
                col_name = cols[ci] if cols and ci < len(cols) else ""
                is_qty = any(q in col_name.lower() for q in ["quantity", "qty", "count"])
                ws.write_number(row, ci, grand_totals[ci], F_GRAND_QTY if is_qty else F_GRAND_NUM)
            else:
                ws.write_blank(row, ci, None, F_GRAND_LBL)
        ws.set_row(row, 15)

    sections_list = data.get("partB", {}).get("sections", [])
    sections = {s["sectionKey"]: s for s in sections_list}

    header_labels = data.get("header", {}).get("columnLabel", [])
    header_values = data.get("header", {}).get("columnData", [])
    footer_labels  = data.get("footer", {}).get("columnLabel", [])
    footer_values  = data.get("footer", {}).get("columnData", [])
    part_a_labels = data.get("partA", {}).get("columnLabel", [])
    part_a_values = data.get("partA", {}).get("columnData", [])
    header_map = {str(k).strip(): v for k, v in zip(header_labels, header_values)}
    part_a_map = {str(k).strip(): v for k, v in zip(part_a_labels, part_a_values)}
    footer_map = {str(k).strip(): v for k, v in zip(footer_labels, footer_values)}
    assessment_year = (
        header_map.get("Assessment Year")
        or header_map.get("Assessment Year ")
        or ""
    )

    # ── Sheet 1: General Info ──────────────────────────────────────────────
    _log("Writing General Info sheet…")
    ws_gi = wb.add_worksheet("General Info")
    ws_gi.hide_gridlines(2)
    ws_gi.set_column(0, 0, 35)
    ws_gi.set_column(1, 1, 60)
    ws_gi.merge_range(0, 0, 0, 1, f"AIS — {assessee_name} — FY {fy}", F_TITLE)
    ws_gi.set_row(0, 28)
    ws_gi.merge_range(
        1, 0, 1, 1,
        "AayDoc Capio™  ·  © 2026  ·  Developed by CA. Deepak Bhholusaria  ·  linkedin.com/in/bhholusaria  ·  deepak@ailearrning.guru",
        F_SUBTITLE)
    ws_gi.set_row(1, 22)

    row_gi = 2
    fields_map = [
        ("ASSESSEE INFORMATION", None),
        ("PAN", "Permanent Account Number (PAN)"),
        ("Aadhaar Number", "Aadhaar Number"),
        ("Name of Assessee", "Name of Assessee"),
        ("Date of Birth", "Date of Birth"),
        ("Mobile Number", "Mobile Number"),
        ("E-mail Address", "E-mail Address"),
        ("Address", "Address"),
        ("REPORT INFORMATION", None),
        ("Financial Year", "__fy__"),
        ("Assessment Year", "__ay__"),
        ("Report Generated On", "__report_ts__"),
    ]
    for label, key in fields_map:
        if key is None:
            ws_gi.merge_range(row_gi, 0, row_gi, 1, label, F_SECTION)
            ws_gi.set_row(row_gi, 16)
        else:
            ws_gi.write(row_gi, 0, label, F_LABEL)
            if key == "__fy__":
                val = fy
            elif key == "__ay__":
                val = assessment_year
            elif key == "__report_ts__":
                val = report_ts
            else:
                val = part_a_map.get(key, "")
            ws_gi.write(row_gi, 1, str(val) if val is not None else "", F_VALUE)
        row_gi += 1

    row_gi += 1
    ws_gi.merge_range(row_gi, 0, row_gi, 1, "File Metadata", F_SECTION)
    ws_gi.set_row(row_gi, 16); row_gi += 1

    meta = data.get("metadata", {})
    for lbl, val in [
        ("PAN (logged in)", meta.get("loggedInPan", "")),
        ("Financial Year", fy),
        ("Download Date", download_date),
        ("JSON Version", meta.get("jsonVersion", "")),
        ("Utility Version", meta.get("utilityVersion", "")),
    ]:
        ws_gi.write(row_gi, 0, lbl, F_LABEL)
        ws_gi.write(row_gi, 1, str(val) if val is not None else "", F_VALUE)
        row_gi += 1

    row_gi += 1
    ws_gi.merge_range(row_gi, 0, row_gi, 1, "File Information", F_SECTION)
    ws_gi.set_row(row_gi, 16); row_gi += 1
    for lbl, val in zip(footer_labels, footer_values):
        ws_gi.write(row_gi, 0, lbl, F_LABEL)
        ws_gi.write(row_gi, 1, str(val) if val is not None else "", F_VALUE)
        row_gi += 1

    row_gi += 1
    ws_gi.merge_range(row_gi, 0, row_gi, 1, "NOTES", F_SECTION)
    row_gi += 1
    notes = (
        "· General information is read from Part A of the AIS JSON.\n"
        "· Aadhaar and email values may be masked by the ITD portal in the source JSON.\n"
        "· All amounts in the workbook are in INR unless stated otherwise.\n"
        "· Summary links jump to the relevant AIS worksheet; detailed rows remain traceable to their source sheets."
    )
    ws_gi.merge_range(row_gi, 0, row_gi, 1, notes, F_NOTES)
    ws_gi.set_row(row_gi, 72)

    # ── Sheet 2: Summary ───────────────────────────────────────────────────
    _log("Writing Summary sheet…")
    SUMMARY_COLS = [
        "Section", "Info Category", "Info Code", "Description",
        "Source", "Amount",
    ]
    ws_sum = wb.add_worksheet("Summary")
    ws_sum.hide_gridlines(2)
    _brand_row(ws_sum, len(SUMMARY_COLS))
    _hdr_row(ws_sum, SUMMARY_COLS)

    row_s = 2
    col_w = {i: min(len(h), 15) for i, h in enumerate(SUMMARY_COLS)}
    sec_labels = {
        "tdsTcs": "B1 — TDS/TCS",
        "sft": "B2 — SFT",
        "paymentOfTaxes": "B3 — Payment of Taxes",
        "demandAndRefund": "B4 — Demand & Refund",
        "other-info": "B7 — Other Info",
    }
    summary_sft_sheet_names = {
        "SFT-005": "SFT-005 (Time Dep)",
        "SFT-006": "SFT-006 (Credit Card)",
        "SFT-008": "SFT-008 (Purchase of Shares)",
        "SFT-010": "SFT-010 (MF Purchase)",
        "SFT-012": "SFT-012 (IMP)",
        "SFT-015": "SFT-015 (Dividend)",
        "SFT-016(SB)": "SFT-016(SB) (Int-SB)",
        "SFT-016(TD)": "SFT-016(TD) (Int-TD)",
        "SFT-016(RD)": "SFT-016(RD) (Int-RD)",
        "SFT-17(Pur)": "SFT-17(Pur) (Sec Buy)",
        "SFT-18(Pur)": "SFT-18(Pur) (MF Buy)",
        "SFT-18(Div)": "SFT-18(Div) (MF Div)",
        "SFT-17-LES(M)": "SFT-17-LES(M) (Eq Sale)",
        "SFT-17-LDB(M)": "SFT-17-LDB(M) (Debenture Sale)",
        "SFT-17-EMF(M)": "SFT-17-EMF(M) (EqMF Sale)",
        "SFT-17-UBT(M)": "SFT-17-UBT(M) (REIT)",
        "SFT-17-OTU(M)": "SFT-17-OTU(M) (Othr Units)",
        "SFT-17-LES(OC)": "SFT-17-LES(OC) (Off-Mkt)",
        "SFT-18-EMF(M)": "SFT-18-EMF(M) (EqMF-RTA)",
        "SFT-18-OTU(M)": "SFT-18-OTU(M) (Othr Units)",
    }

    def _summary_target_sheet(sec_key, info_code):
        if sec_key == "tdsTcs":
            return "TDS-194IA(P) (Property)" if info_code == "TDS-194IA(P)" else "Part B1 (TDS TCS)"
        if sec_key == "sft":
            return summary_sft_sheet_names.get(info_code, f"B2 - {info_code}"[:31])
        if sec_key == "paymentOfTaxes":
            return "Payment of Taxes"
        if sec_key == "demandAndRefund":
            return "Demand and Refund"
        if sec_key == "other-info":
            return "TDS-Ann.II-SAL (Salary)" if info_code == "TDS-Ann.II-SAL" else f"B7 - {info_code}"[:31]
        return None

    summary_groups = {}
    for sec in sections_list:
        sec_key = sec.get("sectionKey", "")
        sec_label = sec_labels.get(sec_key, sec_key)
        for elem in sec.get("elements", []):
            l2 = _get_l2(elem)
            if not l2:
                continue
            l2_amt = _parse_amount(l2.get("amount", "")) or 0.0
            info_code = l2.get("info_code", "")
            info_category = l2.get("category", "")
            description = l2.get("description", "")
            target_sheet = _summary_target_sheet(sec_key, info_code)
            key = (sec_label, info_code, info_category, description, target_sheet)
            vals = [
                sec_label,
                info_category,
                info_code,
                description,
                l2.get("source", ""),
                l2_amt,
                target_sheet,
            ]
            summary_groups.setdefault(key, []).append(vals)

    for (sec_label, info_code, info_category, description, target_sheet), rows in summary_groups.items():
        group_start = row_s
        for vals in rows:
            target = vals[6]
            url = f"internal:'{target}'!A1" if target else None
            for ci, v in enumerate(vals):
                if ci >= len(SUMMARY_COLS):
                    continue
                if url and ci in {2, 3, 4}:
                    ws_sum.write_url(row_s, ci, url, F_DEFAULT, str(v) if v is not None else "")
                else:
                    ws_sum.write(row_s, ci, str(v) if v is not None else "", F_DEFAULT)
                col_w[ci] = max(col_w.get(ci, 0), len(str(v)))
            ws_sum.write_number(row_s, 5, vals[5], F_NUM)
            col_w[5] = max(col_w.get(5, 0), len(f"{vals[5]:,.2f}"))
            row_s += 1

        subtotal_name = info_category or description or sec_label
        subtotal_label = f"Subtotal: {subtotal_name} ({info_code})" if info_code else f"Subtotal: {subtotal_name}"
        ws_sum.merge_range(row_s, 0, row_s, 4, subtotal_label, F_SUBTOT_LBL)
        ws_sum.write_formula(row_s, 5,
            f"=SUM(F{group_start + 1}:F{row_s})",
            F_SUBTOT_NUM)
        ws_sum.set_row(row_s, 14)
        row_s += 1

    _autofit(ws_sum, [col_w.get(i, 8) for i in range(6)])

    # ── Sheet 3: TDS / TCS ────────────────────────────────────────────────
    tds_sec = sections.get("tdsTcs")
    tds_elems = (tds_sec or {}).get("elements", [])

    # Split into standard TDS/TCS and property TDS (194IA(P)) — separate sheets
    tds_standard = [e for e in tds_elems
                    if (_get_l2(e).get("info_code", "") != "TDS-194IA(P)")]
    tds_property = [e for e in tds_elems
                    if (_get_l2(e).get("info_code", "") == "TDS-194IA(P)")]

    # xl_row: 0-based row index → 1-based Excel row string
    def xl_row(r): return r + 1

    def _split_source(raw_src):
        """Split 'NAME (TAN)' → (name, tan). Returns (raw_src, '') if no match."""
        if raw_src.endswith(")") and "(" in raw_src:
            paren = raw_src.rfind("(")
            return raw_src[:paren].strip(), raw_src[paren + 1:-1].strip()
        return raw_src, ""

    def _write_tds_sheet(ws, elems, cols, num_cols_set, grand_lbl,
                         row_writer, label_merge_end):
        """
        Generic deductor-grouped TDS sheet writer.
        row_writer(ws, row, sr, name, tan, l2, l1_idx, data_row, col_w) writes one detail row.
        label_merge_end: last col index (0-based) for subtotal/grand label merge.
        """
        ncols = len(cols)
        ws.hide_gridlines(2)
        _brand_row(ws, ncols)
        _hdr_row(ws, cols)
        ws.freeze_panes(2, 0)

        row = 2
        col_w = {i: min(len(h), 15) for i, h in enumerate(cols)}
        subtotal_rows = []
        sr = 0

        for elem in elems:
            l2 = _get_l2(elem)
            l1_cols, l1_rows = _get_l1(elem)
            l1_rows = _active_rows(l1_cols, l1_rows)
            if not l1_rows:
                continue

            raw_src = l2.get("source", "") if l2 else (elem.get("source", "") or "")
            name, tan = _split_source(raw_src)
            sr += 1
            detail_start = row
            l1_idx = {n: i for i, n in enumerate(l1_cols)}

            for data_row in l1_rows:
                row_writer(ws, row, sr, name, tan, l2, l1_idx, data_row, col_w)
                row += 1

            detail_end = row - 1
            lbl = f"Sr. {sr}  ·  Subtotal — {name}"
            ws.write_blank(row, 0, None, F_SUBTOT_LBL)
            ws.merge_range(row, 1, row, label_merge_end, lbl, F_SUBTOT_LBL)
            for ci in num_cols_set:
                col_letter = chr(ord('A') + ci)
                ws.write_formula(row, ci,
                    f"=SUM({col_letter}{xl_row(detail_start)}:{col_letter}{xl_row(detail_end)})",
                    F_SUBTOT_NUM)
            for ci in range(label_merge_end + 1, ncols):
                if ci not in num_cols_set:
                    ws.write_blank(row, ci, None, F_SUBTOT_LBL)
            ws.set_row(row, 14)
            col_w[1] = max(col_w.get(1, 0), len(lbl))
            subtotal_rows.append(row)
            row += 1

        ws.write_blank(row, 0, None, F_GRAND_LBL)
        ws.merge_range(row, 1, row, label_merge_end, grand_lbl, F_GRAND_LBL)
        for ci in num_cols_set:
            col_letter = chr(ord('A') + ci)
            ws.write_formula(row, ci,
                "=" + "+".join(f"{col_letter}{xl_row(sr_row)}" for sr_row in subtotal_rows),
                F_GRAND_NUM)
        for ci in range(label_merge_end + 1, ncols):
            if ci not in num_cols_set:
                ws.write_blank(row, ci, None, F_GRAND_LBL)
        ws.set_row(row, 15)
        col_w[1] = max(col_w.get(1, 0), len(grand_lbl))
        _autofit(ws, [col_w.get(i, 8) for i in range(ncols)])

    # ── Standard TDS / TCS sheet ──────────────────────────────────────────
    if tds_standard:
        _log("Writing TDS/TCS sheet…")
        STD_COLS = [
            "Sr.", "Deductor / Source", "TAN", "Info Code", "Description",
            "TSN", "Quarter", "Date of Payment/Credit",
            "Amount Paid/Credited (Rs.)", "TDS/TCS Deducted (Rs.)", "TDS/TCS Deposited (Rs.)",
            "Status",
        ]
        STD_NUM = {8, 9, 10}

        def _std_row(ws, row, sr, name, tan, l2, l1_idx, data_row, col_w):
            def _c(col): i = l1_idx.get(col); return data_row[i] if i is not None and i < len(data_row) else ""
            def _first_present(*cols):
                for col in cols:
                    val = _c(col)
                    if val != "":
                        return val
                return ""
            info_code   = l2.get("info_code", "")
            description = l2.get("description", "")
            date_value = _first_present(
                "Date of Payment/Credit",
                "Date of Receipt/ Debit",
                "Date of Receipt/Debit",
            )
            ws.write(row, 0, sr,            F_DEFAULT)
            ws.write(row, 1, name,          F_DEFAULT)
            ws.write(row, 2, tan,           F_DEFAULT)
            ws.write(row, 3, info_code,     F_DEFAULT)
            ws.write(row, 4, description,   F_DEFAULT)
            ws.write(row, 5, _c("TSN"),                    F_DEFAULT)
            ws.write(row, 6, _c("Quarter"),                F_DEFAULT)
            ws.write(row, 7, date_value,                   F_DEFAULT)
            for ci, col, fallbacks in [
                (8, "Amount Paid/Credited", ["Amount Received/Debited"]),
                (9, "TDS Deducted", ["Tax Collected"]),
                (10, "TDS Deposited", ["TCS Deposited"]),
            ]:
                val = _c(col)
                if val == "":
                    for fallback in fallbacks:
                        val = _c(fallback)
                        if val != "":
                            break
                amt = _parse_amount(str(val))
                ws.write_number(row, ci, amt if amt is not None else 0, F_NUM)
            ws.write(row, 11, _c("Status"), F_DEFAULT)
            for ci, v in enumerate([sr, name, tan, info_code, description,
                                     _c("TSN"), _c("Quarter"), date_value]):
                col_w[ci] = max(col_w.get(ci, 0), len(str(v)))

        ws_tds = wb.add_worksheet("Part B1 (TDS TCS)")
        _write_tds_sheet(ws_tds, tds_standard, STD_COLS, STD_NUM,
                         "GRAND TOTAL — Part B1 (TDS-TCS)",
                         _std_row, label_merge_end=7)

    # ── TDS on Property 194IA(P) sheet ────────────────────────────────────
    if tds_property:
        _log("Writing TDS on Property (194IA) sheet…")
        PROP_COLS = [
            "Sr.", "Buyer Name", "Buyer PAN", "Info Code",
            "TSN", "Ack. No.", "Property Address",
            "Date of Payment/Credit",
            "Total Transaction Amount (Rs.)", "TDS Deposited (Rs.)",
            "Status",
        ]
        PROP_NUM = {8, 9}

        def _prop_row(ws, row, sr, name, tan, l2, l1_idx, data_row, col_w):
            def _c(col): i = l1_idx.get(col); return data_row[i] if i is not None and i < len(data_row) else ""
            info_code = l2.get("info_code", "")
            ws.write(row, 0, sr,            F_DEFAULT)
            ws.write(row, 1, name,          F_DEFAULT)
            ws.write(row, 2, tan,           F_DEFAULT)
            ws.write(row, 3, info_code,     F_DEFAULT)
            ws.write(row, 4, _c("TSN"),                    F_DEFAULT)
            ws.write(row, 5, _c("Acknowledgement Number"), F_DEFAULT)
            ws.write(row, 6, _c("Property Address"),       F_DEFAULT)
            ws.write(row, 7, _c("Date of Payment/Credit"), F_DEFAULT)
            for ci, col in [(8, "Amount Paid/Credited"), (9, "TDS Deposited")]:
                amt = _parse_amount(str(_c(col)))
                ws.write_number(row, ci, amt if amt is not None else 0, F_NUM)
            ws.write(row, 10, _c("Status"), F_DEFAULT)
            for ci, v in enumerate([sr, name, tan, info_code,
                                     _c("TSN"), _c("Acknowledgement Number"),
                                     _c("Property Address"), _c("Date of Payment/Credit")]):
                col_w[ci] = max(col_w.get(ci, 0), len(str(v)))

        ws_prop = wb.add_worksheet("TDS-194IA(P) (Property)")
        _write_tds_sheet(ws_prop, tds_property, PROP_COLS, PROP_NUM,
                         "GRAND TOTAL — TDS-194IA(P) (Property)",
                         _prop_row, label_merge_end=7)

    # ── SFT — one sheet per info_code ─────────────────────────────────────
    sft_sec = sections.get("sft")
    sft_elems = (sft_sec or {}).get("elements", [])

    # Group elements by info_code, preserving order of first appearance
    sft_by_code: dict[str, list] = {}
    for elem in sft_elems:
        code = _infer_info_code(elem)
        if code:
            sft_by_code.setdefault(code, []).append(elem)

    # ── Per-code column definitions ────────────────────────────────────────
    # NUM_KW used for dynamic sheets to detect numeric columns by name
    _SFT_NUM_KW = {"amount", "value", "consideration", "price",
                   "dividend", "interest", "payment", "quantity", "stt"}

    # Columns shared by SFT-005, SFT-006, SFT-008, SFT-010 (person-level SFT)
    _SFT_PRSN_BASE = ["TSN", "Reported On",
                      "Gross amount received from the person",
                      "Gross amount paid to the person", "Status"]
    _SFT_PRSN_NUM  = {"Gross amount received from the person",
                      "Gross amount paid to the person"}

    # SFT-006 adds one extra column
    _SFT_006_COLS = ["TSN", "Reported On",
                     "Gross amount received from the person",
                     "Gross amount received from the person in cash",
                     "Gross amount paid to the person", "Status"]
    _SFT_006_NUM  = {"Gross amount received from the person",
                     "Gross amount received from the person in cash",
                     "Gross amount paid to the person"}

    # SFT-012 — immovable property
    _SFT_012_COLS = ["TSN", "Reported On", "Property Address", "Property type",
                     "Transaction Type", "Transaction Date", "Transaction amount",
                     "Value of Property for Stamp Duty", "Party Count",
                     "Transaction amount assigned", "Status"]
    _SFT_012_NUM  = {"Transaction amount", "Value of Property for Stamp Duty",
                     "Transaction amount assigned"}

    # SFT-015 — dividend from companies
    _SFT_015_COLS = ["TSN", "Reported On", "Dividend Amount", "Status"]
    _SFT_015_NUM  = {"Dividend Amount"}

    # SFT-016 variants (SB / TD / RD) — same columns
    _SFT_016_COLS = ["TSN", "Reported On", "Account Number", "Account Type",
                     "Interest amount", "Status"]
    _SFT_016_NUM  = {"Interest amount"}

    # SFT-17(Pur) — depository purchase aggregate
    _SFT_17PUR_COLS = ["TSN", "Quarter", "Client ID", "Holder Flag",
                       "Market Purchase", "Market Sales", "Status"]
    _SFT_17PUR_NUM  = {"Market Purchase", "Market Sales"}

    # SFT-18(Pur) — RTA purchase aggregate
    _SFT_18PUR_COLS = ["TSN", "Quarter", "Client ID", "AMC Name (Code)",
                       "Holder Flag", "Total Purchase Amount", "Total Sales Value", "Status"]
    _SFT_18PUR_NUM  = {"Total Purchase Amount", "Total Sales Value"}

    # SFT-18(Div) — MF dividend via RTA
    _SFT_18DIV_COLS = ["TSN", "Quarter", "Client ID", "AMC Name (Code)",
                       "No. of Holders", "Holder Flag", "Dividend Amount", "Status"]
    _SFT_18DIV_NUM  = {"Dividend Amount"}

    # SFT-17-*(M) via Depository — superset with ISIN split out
    _SFT_17M_SUPERSET = [
        "TSN", "Date of Sale/Transfer", "ISIN", "Security Name",
        "Security Class", "Debit Type", "Credit Type", "Asset Type",
        "Quantity", "Sale Price Per unit", "Sales Consideration",
        "Cost of Acquisition", "Unit FMV", "Fair Market Value",
        "Indexed Cost of Acquisition", "Status",
    ]
    _SFT_17M_NUM = {"Quantity", "Sale Price Per unit", "Sales Consideration",
                    "Cost of Acquisition", "Unit FMV", "Fair Market Value",
                    "Indexed Cost of Acquisition"}

    # SFT-17-LES(OC) — off-market credit, ISIN split out
    _SFT_17OC_COLS = ["TSN", "Transferor Name (PAN)", "Date of Transfer",
                      "Nature of Transfer", "ISIN", "Security Name",
                      "Security Class", "Quantity Transferred", "EOD Price per Unit",
                      "End of the Day Value", "Consideration", "Status"]
    _SFT_17OC_NUM  = {"Quantity Transferred", "EOD Price per Unit",
                      "End of the Day Value", "Consideration"}

    # SFT-18-*(M) via RTA — superset with ISIN split out (includes AMC Name + STT)
    _SFT_18M_SUPERSET = [
        "TSN", "AMC Name (Code)", "Date of Sale/Transfer",
        "Security Class", "ISIN", "Security Name",
        "Debit Type", "Credit Type", "Asset Type",
        "Quantity", "Sale Price Per unit", "Sales Consideration", "STT",
        "Cost of Acquisition", "Unit FMV", "Fair Market Value",
        "Indexed Cost of Acquisition", "Status",
    ]
    _SFT_18M_NUM = {"Quantity", "Sale Price Per unit", "Sales Consideration", "STT",
                    "Cost of Acquisition", "Unit FMV", "Fair Market Value",
                    "Indexed Cost of Acquisition"}

    # Map info_code → (sheet_name, prefix_cols, data_superset, num_set, col_rename)
    # prefix_cols: columns written before the data superset (Source always first for all sheets)
    # For sheets where Source IS a data column, prefix = ["Sr.", "Source"]
    # col_rename: optional dict for _map_to_superset
    _SFT_SHEET_DEF = {
        "SFT-005":        ("SFT-005 (Time Dep)",               _SFT_PRSN_BASE,    _SFT_PRSN_NUM,   None),
        "SFT-006":        ("SFT-006 (Credit Card)",            _SFT_006_COLS,     _SFT_006_NUM,    None),
        "SFT-008":        ("SFT-008 (Purchase of Shares)",     _SFT_PRSN_BASE,    _SFT_PRSN_NUM,   None),
        "SFT-010":        ("SFT-010 (MF Purchase)",            _SFT_PRSN_BASE,    _SFT_PRSN_NUM,   None),
        "SFT-012":        ("SFT-012 (IMP)",                    _SFT_012_COLS,     _SFT_012_NUM,    None),
        "SFT-015":        ("SFT-015 (Dividend)",               _SFT_015_COLS,     _SFT_015_NUM,    None),
        "SFT-016(SB)":    ("SFT-016(SB) (Int-SB)",             _SFT_016_COLS,     _SFT_016_NUM,    None),
        "SFT-016(TD)":    ("SFT-016(TD) (Int-TD)",             _SFT_016_COLS,     _SFT_016_NUM,    None),
        "SFT-016(RD)":    ("SFT-016(RD) (Int-RD)",             _SFT_016_COLS,     _SFT_016_NUM,    None),
        "SFT-17(Pur)":    ("SFT-17(Pur) (Sec Buy)",            _SFT_17PUR_COLS,   _SFT_17PUR_NUM,  None),
        "SFT-18(Pur)":    ("SFT-18(Pur) (MF Buy)",             _SFT_18PUR_COLS,   _SFT_18PUR_NUM,  None),
        "SFT-18(Div)":    ("SFT-18(Div) (MF Div)",             _SFT_18DIV_COLS,   _SFT_18DIV_NUM,  None),
        "SFT-17-LES(M)":  ("SFT-17-LES(M) (Eq Sale)",          _SFT_17M_SUPERSET, _SFT_17M_NUM,    None),
        "SFT-17-LDB(M)":  ("SFT-17-LDB(M) (Debenture Sale)",   _SFT_17M_SUPERSET, _SFT_17M_NUM,    None),
        "SFT-17-EMF(M)":  ("SFT-17-EMF(M) (EqMF Sale)",        _SFT_17M_SUPERSET, _SFT_17M_NUM,    None),
        "SFT-17-UBT(M)":  ("SFT-17-UBT(M) (REIT)",             _SFT_17M_SUPERSET, _SFT_17M_NUM,    None),
        "SFT-17-OTU(M)":  ("SFT-17-OTU(M) (Othr Units)",       _SFT_17M_SUPERSET, _SFT_17M_NUM,    None),
        "SFT-17-LES(OC)": ("SFT-17-LES(OC) (Off-Mkt)",         _SFT_17OC_COLS,    _SFT_17OC_NUM,   None),
        "SFT-18-EMF(M)":  ("SFT-18-EMF(M) (EqMF-RTA)",         _SFT_18M_SUPERSET, _SFT_18M_NUM,    None),
        "SFT-18-OTU(M)":  ("SFT-18-OTU(M) (Othr Units)",       _SFT_18M_SUPERSET, _SFT_18M_NUM,    None),
    }

    # Codes that use flat detail rows + summary block below (no per-group subtotals)
    _SFT_FLAT_SUMMARY = {"SFT-015", "SFT-016(SB)", "SFT-016(TD)", "SFT-016(RD)", "SFT-18(Div)"}



    # Tracks grand total row per sheet name so audit trail can reference it
    _sheet_grand_row: dict[str, int] = {}

    def _write_sft_flat_summary(ws_name, elems, superset, num_set, col_rename=None):
        """
        Flat detail rows (no subtotals between groups), then grand total with count.
        Used for income-type SFTs: SFT-015, SFT-016(SB/TD/RD), SFT-18(Div).
        Columns: Sr. | Source | Count (from l2) | ...l1 data cols...
        """
        n_prefix = 3  # Sr. | Source | Count
        full_cols = ["Sr.", "Source", "Count"] + superset
        ncols = len(full_cols)
        col_w = {i: min(len(h), 15) for i, h in enumerate(full_cols)}
        num_col_indices = sorted(i + n_prefix for i, c in enumerate(superset) if c in num_set)

        ws = wb.add_worksheet(ws_name)
        ws.hide_gridlines(2)
        _brand_row(ws, ncols)
        _hdr_row(ws, full_cols)
        ws.freeze_panes(2, 0)

        row = 2
        sr = 0
        detail_start = row
        # Track (source, row_start, row_end) per element for summary SUMIF
        source_ranges: list[tuple[str, int, int]] = []

        for elem in elems:
            l2 = _get_l2(elem)
            l1_cols, l1_rows = _get_l1(elem)
            l1_rows = _active_rows(l1_cols, l1_rows)
            if not l1_rows:
                continue

            source = l2.get("source", "") if l2 else (elem.get("source", "") or "")
            count_val = _parse_amount(str(l2.get("count", "") or "")) or ""
            sr += 1
            elem_start = row
            l1_idx = {n: i for i, n in enumerate(l1_cols)}

            for data_row in l1_rows:
                def _c(col, _idx=l1_idx, _row=data_row):
                    i = _idx.get(col)
                    if i is None and col_rename:
                        for k, v in col_rename.items():
                            if v == col:
                                i = _idx.get(k)
                                break
                    return _row[i] if i is not None and i < len(_row) else ""

                ws.write(row, 0, sr,     F_DEFAULT)
                ws.write(row, 1, source, F_DEFAULT)
                if count_val != "":
                    ws.write_number(row, 2, int(count_val), F_DEFAULT)
                else:
                    ws.write_blank(row, 2, None, F_DEFAULT)
                col_w[0] = max(col_w.get(0, 0), len(str(sr)))
                col_w[1] = max(col_w.get(1, 0), len(source))
                col_w[2] = max(col_w.get(2, 0), len(str(count_val)))

                raw_vals = [data_row[l1_idx[c]] if c in l1_idx and l1_idx[c] < len(data_row) else ""
                            for c in l1_cols]
                mapped = _map_to_superset(raw_vals, l1_cols, superset, col_rename)

                _sec_raw = _c("Security Name (Security Code)")
                _isin, _secname = _split_security_name(str(_sec_raw)) if _sec_raw else ("", "")

                for si, val in enumerate(mapped):
                    ci = si + n_prefix
                    col_name = superset[si]
                    if col_name == "ISIN":
                        val = _isin
                    elif col_name == "Security Name":
                        val = _secname
                    if col_name in num_set:
                        amt = _parse_amount(str(val))
                        ws.write_number(row, ci, amt if amt is not None else 0, F_NUM)
                    else:
                        ws.write(row, ci, str(val) if val is not None else "", F_DEFAULT)
                    col_w[ci] = max(col_w.get(ci, 0), len(str(val)))
                row += 1

            source_ranges.append((source, elem_start, row - 1))

        detail_end = row - 1
        total_txn = detail_end - detail_start + 1  # total active transaction rows
        merge_end = max(1, min(num_col_indices) - 1) if num_col_indices else ncols - 1

        # ── Grand total — sums all detail rows, with count label ──
        grand_lbl = f"GRAND TOTAL — {ws_name}"
        count_lbl = f"Count: {total_txn}"
        ws.write(row, 0, count_lbl, F_GRAND_LBL)
        ws.merge_range(row, 1, row, merge_end, grand_lbl, F_GRAND_LBL)
        for ci in num_col_indices:
            col_letter = chr(ord('A') + ci)
            ws.write_formula(row, ci,
                f"=SUM({col_letter}{xl_row(detail_start)}:{col_letter}{xl_row(detail_end)})",
                F_GRAND_NUM)
        ws.set_row(row, 15)
        col_w[1] = max(col_w.get(1, 0), len(grand_lbl))
        _sheet_grand_row[ws_name] = row
        _autofit(ws, [col_w.get(i, 8) for i in range(ncols)])

    def _write_sft_sheet(ws_name, elems, superset, num_set, col_rename=None):
        """Write a single SFT code sheet. Flat rows by source, grand total only."""
        n_prefix = 2  # Sr. | Source
        full_cols = ["Sr.", "Source"] + superset
        ncols = len(full_cols)
        col_w = {i: min(len(h), 15) for i, h in enumerate(full_cols)}
        num_col_indices = {i + n_prefix for i, c in enumerate(superset) if c in num_set}

        ws = wb.add_worksheet(ws_name)
        ws.hide_gridlines(2)
        _brand_row(ws, ncols)
        _hdr_row(ws, full_cols)
        ws.freeze_panes(2, 0)

        row = 2
        detail_start = row
        sr = 0

        for elem in elems:
            l2 = _get_l2(elem)
            l1_cols, l1_rows = _get_l1(elem)
            l1_rows = _active_rows(l1_cols, l1_rows)
            if not l1_rows:
                continue

            source = l2.get("source", "") if l2 else (elem.get("source", "") or "")
            sr += 1
            l1_idx = {n: i for i, n in enumerate(l1_cols)}

            for data_row in l1_rows:
                def _c(col, _idx=l1_idx, _row=data_row):
                    i = _idx.get(col)
                    if i is None and col_rename:
                        for k, v in col_rename.items():
                            if v == col:
                                i = _idx.get(k)
                                break
                    return _row[i] if i is not None and i < len(_row) else ""

                ws.write(row, 0, sr,     F_DEFAULT)
                ws.write(row, 1, source, F_DEFAULT)
                col_w[0] = max(col_w.get(0, 0), len(str(sr)))
                col_w[1] = max(col_w.get(1, 0), len(source))

                raw_vals = [data_row[l1_idx[c]] if c in l1_idx and l1_idx[c] < len(data_row) else ""
                            for c in l1_cols]
                mapped = _map_to_superset(raw_vals, l1_cols, superset, col_rename)

                _sec_raw = _c("Security Name (Security Code)")
                _isin, _secname = _split_security_name(str(_sec_raw)) if _sec_raw else ("", "")

                for si, val in enumerate(mapped):
                    ci = si + n_prefix
                    col_name = superset[si]
                    if col_name == "ISIN":
                        val = _isin
                    elif col_name == "Security Name":
                        val = _secname
                    if col_name in num_set:
                        amt = _parse_amount(str(val))
                        ws.write_number(row, ci, amt if amt is not None else 0, F_NUM)
                    else:
                        ws.write(row, ci, str(val) if val is not None else "", F_DEFAULT)
                    col_w[ci] = max(col_w.get(ci, 0), len(str(val)))
                row += 1

        detail_end = row - 1
        grand_lbl = f"GRAND TOTAL — {ws_name}"
        merge_end = max(1, min(num_col_indices) - 1) if num_col_indices else ncols - 1
        ws.write_blank(row, 0, None, F_GRAND_LBL)
        ws.merge_range(row, 1, row, merge_end, grand_lbl, F_GRAND_LBL)
        for ci in num_col_indices:
            col_letter = chr(ord('A') + ci)
            col_name = full_cols[ci]
            is_qty = any(q in col_name.lower() for q in ["quantity", "qty", "count"])
            fmt = F_GRAND_QTY if is_qty else F_GRAND_NUM
            ws.write_formula(row, ci,
                f"=SUM({col_letter}{xl_row(detail_start)}:{col_letter}{xl_row(detail_end)})",
                fmt)
        ws.set_row(row, 15)
        _sheet_grand_row[ws_name] = row
        _autofit(ws, [col_w.get(i, 8) for i in range(ncols)])

    # ── Tab colours per group ─────────────────────────────────────────────
    # GENERAL=grey, TDS/TAX=red, INCOME=orange, INFORMATIONAL=purple,
    # PURCHASE=blue, SALE/CAPITAL GAINS=green
    TC_GENERAL  = "#808080"
    TC_TAX      = "#C0504D"
    TC_INCOME   = "#E36C09"
    TC_INFO     = "#7030A0"
    TC_PURCHASE = "#17375E"
    TC_SALE     = "#0E6674"

    # Apply colour to already-written General Info and Summary tabs
    wb.get_worksheet_by_name("General Info").set_tab_color(TC_GENERAL)
    wb.get_worksheet_by_name("Summary").set_tab_color(TC_GENERAL)
    if tds_standard:
        wb.get_worksheet_by_name("Part B1 (TDS TCS)").set_tab_color(TC_TAX)
    if tds_property:
        wb.get_worksheet_by_name("TDS-194IA(P) (Property)").set_tab_color(TC_TAX)

    # Helper: write one SFT sheet with tab colour
    def _write_sft(code, tab_color):
        elems = sft_by_code.get(code)
        if not elems:
            return
        defn = _SFT_SHEET_DEF.get(code)
        if defn:
            ws_name, superset, num_set, col_rename = defn
            _log(f"Writing {ws_name}…")
            if code in _SFT_FLAT_SUMMARY:
                _write_sft_flat_summary(ws_name, elems, superset, num_set, col_rename)
            else:
                _write_sft_sheet(ws_name, elems, superset, num_set, col_rename)
        else:
            ws_name = f"B2 - {code}"[:31]
            _log(f"Writing {ws_name} (dynamic)…")
            dyn_sup = _build_dynamic_superset(elems)
            dyn_num = {c for c in dyn_sup if any(k in c.lower() for k in _SFT_NUM_KW)}
            _write_sft_sheet(ws_name, elems, dyn_sup, dyn_num, None)
        ws = wb.get_worksheet_by_name(ws_name)
        if ws:
            ws.set_tab_color(tab_color)

    # ── Payment of Taxes (TDS/TAX group) ─────────────────────────────────
    tax_sec = sections.get("paymentOfTaxes")
    tax_elems = (tax_sec or {}).get("elements", [])
    tax_rows = []
    tax_cols = []
    for elem in tax_elems:
        cols = elem.get("columnLabel", [])
        rows = elem.get("columnData", [])
        if cols and not tax_cols:
            tax_cols = [str(c) for c in cols]
        tax_rows.extend(rows)

    if tax_rows:
        _log("Writing Payment of Taxes sheet…")
        TAX_NUM_COLS = {"Tax (A)", "Surcharge (B)", "Education Cess (C)",
                        "Others (D)", "Total (A+B+C+D)"}
        ncols = len(tax_cols)
        ws_tax = wb.add_worksheet("Payment of Taxes")
        ws_tax.set_tab_color(TC_TAX)
        ws_tax.hide_gridlines(2)
        _brand_row(ws_tax, ncols)
        _hdr_row(ws_tax, tax_cols)

        row_tx = 2
        col_w = {i: min(len(h), 15) for i, h in enumerate(tax_cols)}
        grand = {}

        for vals in tax_rows:
            for ci, (v, cname) in enumerate(zip(vals, tax_cols)):
                if cname in TAX_NUM_COLS:
                    amt = _parse_amount(str(v))
                    if amt is not None:
                        ws_tax.write_number(row_tx, ci, amt, F_NUM)
                        grand[ci] = grand.get(ci, 0) + amt
                    else:
                        ws_tax.write(row_tx, ci, str(v) if v else "", F_DEFAULT)
                else:
                    ws_tax.write(row_tx, ci, str(v) if v else "", F_DEFAULT)
                col_w[ci] = max(col_w.get(ci, 0), len(str(v)))
            row_tx += 1

        _grand_total_row(ws_tax, row_tx, ncols, grand, col_w, tax_cols)
        _autofit(ws_tax, [col_w.get(i, 8) for i in range(ncols)])

    # ── Generic flat-table writer for B4, B5, B6 ─────────────────────────
    def _write_generic_section(ws_name: str, section: dict | None, tab_color: str = TC_GENERAL):
        if not section:
            return
        elems = [e for e in section.get("elements", [])
                 if e.get("l1") and (e["l1"].get("columnData") or [])]
        if not elems:
            return

        _log(f"Writing {ws_name} sheet…")
        dyn_sup = _build_dynamic_superset(elems)
        PREFIX = ["Info Code", "Description", "Source"]
        COLS = PREFIX + dyn_sup
        NUM_KW = {"amount", "salary", "perquisite", "profit", "value",
                  "consideration", "interest", "dividend", "tax", "gross"}
        NUM_COLS = {c for c in dyn_sup if any(k in c.lower() for k in NUM_KW)}
        ncols = len(COLS)

        ws = wb.add_worksheet(ws_name)
        ws.set_tab_color(tab_color)
        ws.hide_gridlines(2)
        _brand_row(ws, ncols)
        _hdr_row(ws, COLS)

        row_g = 2
        col_w = {i: min(len(h), 15) for i, h in enumerate(COLS)}
        grand = {}

        for elem in elems:
            l2 = _get_l2(elem)
            l1_cols, l1_rows = _get_l1(elem)
            l1_rows = _active_rows(l1_cols, l1_rows)
            prefix = [l2.get("info_code",""), l2.get("description",""), l2.get("source","")]
            row_g, totals = _write_group(
                ws, row_g, prefix, l1_cols, l1_rows, dyn_sup, None, NUM_COLS, col_w)
            for k, v in totals.items():
                grand[k] = grand.get(k, 0) + v
            if l1_rows:
                src = l2.get("source","")[:30]
                lbl = f"Subtotal — {l2.get('info_code','')}  [{src}]"
                _subtotal_row(ws, row_g, ncols, lbl, totals, col_w, COLS)
                row_g += 1

        if grand:
            _grand_total_row(ws, row_g, ncols, grand, col_w, COLS)
        _autofit(ws, [col_w.get(i, 8) for i in range(ncols)])

    # ── B7 — Other Info: collect by code ─────────────────────────────────
    other_sec = sections.get("other-info")
    other_elems = [e for e in (other_sec or {}).get("elements", [])
                   if e.get("l1") and (e.get("l1") or {}).get("columnData")]
    other_by_code: dict[str, list] = {}
    for elem in other_elems:
        l2 = _get_l2(elem)
        code = l2.get("info_code", "")
        if code:
            other_by_code.setdefault(code, []).append(elem)

    def _write_b7_code(code, tab_color):
        elems = other_by_code.get(code)
        if not elems:
            return
        if code == "TDS-Ann.II-SAL":
            SAL_COLS = [
                "Sr.", "Source",
                "TSN", "Employment Start Date", "Employment End Date",
                "Gross Salary u/s 17(1)", "Value of perquisites u/s 17(2)",
                "Profits in lieu of salary u/s 17(3)", "Gross Salary", "Status",
            ]
            SAL_NUM = {"Gross Salary u/s 17(1)", "Value of perquisites u/s 17(2)",
                       "Profits in lieu of salary u/s 17(3)", "Gross Salary"}
            SAL_SUPERSET = SAL_COLS[2:]
            _log("Writing TDS-Ann.II-SAL (Salary) sheet…")
            _write_sft_sheet("TDS-Ann.II-SAL (Salary)", elems, SAL_SUPERSET, SAL_NUM, None)
            ws = wb.get_worksheet_by_name("TDS-Ann.II-SAL (Salary)")
        else:
            ws_name = f"B7 - {code}"[:31]
            _log(f"Writing {ws_name} sheet…")
            dyn_sup = _build_dynamic_superset(elems)
            dyn_num = {c for c in dyn_sup
                       if any(k in c.lower() for k in {"amount", "salary", "gross",
                                                        "perquisite", "profit", "value"})}
            _write_sft_sheet(ws_name, elems, dyn_sup, dyn_num, None)
            ws = wb.get_worksheet_by_name(ws_name)
        if ws:
            ws.set_tab_color(tab_color)

    # ══ Write sheets in mockup group order ══
    # INCOME group
    _write_b7_code("TDS-Ann.II-SAL", TC_INCOME)
    for b7_code in [c for c in other_by_code if c != "TDS-Ann.II-SAL"]:
        _write_b7_code(b7_code, TC_INCOME)
    for code in ["SFT-015", "SFT-016(SB)", "SFT-016(TD)", "SFT-016(RD)", "SFT-18(Div)"]:
        _write_sft(code, TC_INCOME)

    # INFORMATIONAL group
    for code in ["SFT-005", "SFT-006", "SFT-012"]:
        _write_sft(code, TC_INFO)

    # PURCHASE group
    for code in ["SFT-008", "SFT-010", "SFT-17(Pur)", "SFT-18(Pur)"]:
        _write_sft(code, TC_PURCHASE)

    # SALE / CAPITAL GAINS group
    for code in [
        "SFT-17-LES(M)", "SFT-17-LDB(M)", "SFT-17-EMF(M)", "SFT-17-UBT(M)",
        "SFT-17-OTU(M)", "SFT-17-LES(OC)", "SFT-18-EMF(M)", "SFT-18-OTU(M)",
    ]:
        _write_sft(code, TC_SALE)

    # Any remaining unknown SFT codes
    known_codes = {
        "SFT-015", "SFT-016(SB)", "SFT-016(TD)", "SFT-016(RD)", "SFT-18(Div)",
        "SFT-005", "SFT-006", "SFT-008", "SFT-012",
        "SFT-010", "SFT-17(Pur)", "SFT-18(Pur)",
        "SFT-17-LES(M)", "SFT-17-LDB(M)", "SFT-17-EMF(M)", "SFT-17-UBT(M)",
        "SFT-17-OTU(M)", "SFT-17-LES(OC)", "SFT-18-EMF(M)", "SFT-18-OTU(M)",
    }
    for code in sft_by_code:
        if code not in known_codes:
            _write_sft(code, TC_GENERAL)

    # ── Capital Market — Consolidated ────────────────────────────────────
    # Col index map (0-based):
    #  A=0  SFT Code        B=1  Sr.              C=2  Source
    #  D=3  TSN             E=4  AMC Name(Code)   F=5  Date of Sale/Transfer
    #  G=6  ISIN            H=7  Security Name    I=8  Security Class
    #  J=9  Debit Type      K=10 Credit Type      L=11 Asset Type
    #  M=12 Quantity        N=13 Sale Price/unit
    #  O=14 Gross Sale Consideration              P=15 STT
    #  Q=16 Gross Cost of Acquisition             R=17 FMV 31-Jan-2018 (per unit)
    #  S=18 Total FMV u/s 55(2)(ac) = M×R        T=19 Adj. FMV (lower of O & S)
    #  U=20 Adj. Cost (no indexation)             V=21 Cost with Indexation
    #  W=22 Indexed Cost of Acquisition           X=23 Transfer Expenditure
    #  Y=24 STCG (Rs.)     Z=25 LTCG w/o Idx     AA=26 LTCG with Idx
    #  AB=27 Tax @10%      AC=28 Status
    CM_COLS = [
        "SFT Code", "Sr.", "Source", "TransID", "AMC Name (Code)", 
        "Debit Type", "Credit Type", "Date of Sale/Transfer", "ISIN", "Security Name", 
        "Security Class", "Asset Type", "Quantity", "Sale Price (Per unit)", "Sale Consideration (net)", 
        "STT", "Gross Cost of Acquisition (w/o index)", "Indexed Cost of Acquisition", "FMV 31-Jan-2018 (per unit)", "FMV 31-Jan-2018 (Total)", 
        "Assets Eligible for GrandFathering", "Effetive FMV 31-03-2028 for long term assets", "Adj. FMV (lower of Sale & FMV)", 
        "Adj. Cost of Acquisition (no indexation) (higher of Adj. FMV or Actual CoA)", "Capital Gain (w/o Indexation)", "Capital Gain (w/ Indexation)", 
        "STCG (Rs.)", "LTCG w/o Indexation (Rs.)", "LTCG with Indexation (Rs.)", "Status"
    ]
    # Column letter helper (0-based index → Excel letter, supports AA etc.)
    def _col_letter(idx):
        if idx < 26:
            return chr(ord('A') + idx)
        return chr(ord('A') + idx // 26 - 1) + chr(ord('A') + idx % 26)
    # (sft_code, individual_sheet_name)
    CM_SOURCES = [
        ("SFT-17-LES(M)",  "SFT-17-LES(M) (Eq Sale)"),
        ("SFT-17-LDB(M)",  "SFT-17-LDB(M) (Debenture Sale)"),
        ("SFT-17-EMF(M)",  "SFT-17-EMF(M) (EqMF Sale)"),
        ("SFT-17-UBT(M)",  "SFT-17-UBT(M) (REIT)"),
        ("SFT-17-OTU(M)",  "SFT-17-OTU(M) (Othr Units)"),
        ("SFT-17-LES(OC)", "SFT-17-LES(OC) (Off-Mkt)"),
        ("SFT-18-EMF(M)",  "SFT-18-EMF(M) (EqMF-RTA)"),
        ("SFT-18-OTU(M)",  "SFT-18-OTU(M) (Othr Units)"),
    ]

    # Collect data from individual sheets that actually exist
    cm_groups = []  # list of (sft_code, ind_sheet_name, [row_dicts])
    for sft_code, ind_name in CM_SOURCES:
        src_ws = wb.get_worksheet_by_name(ind_name)
        if src_ws is None:
            continue
        # read header row (row index 1, 0-based) to get column positions
        # xlsxwriter stores data internally — we need to pull from sft_by_code instead
        elems = sft_by_code.get(sft_code, [])
        if not elems:
            continue
        cm_groups.append((sft_code, ind_name, elems))

    if cm_groups:
        _log("Writing ⭐ Capital Market (All) sheet…")
        CM_WS_NAME = "⭐ Capital Market (All)"
        ncols_cm = len(CM_COLS)
        CM_IDEAL_WIDTHS = [
            14,  # SFT Code
            5,   # Sr.
            12,  # Source
            14,  # TransID
            20,  # AMC Name (Code)
            10,  # Debit Type
            10,  # Credit Type
            13,  # Date of Sale/Transfer
            13,  # ISIN
            25,  # Security Name
            18,  # Security Class
            12,  # Asset Type
            10,  # Quantity
            12,  # Sale Price (Per unit)
            16,  # Sale Consideration (net)
            8,   # STT
            16,  # Gross Cost of Acquisition (w/o index)
            16,  # Indexed Cost of Acquisition
            12,  # FMV 31-Jan-2018 (per unit)
            15,  # FMV 31-Jan-2018 (Total)
            15,  # Assets Eligible for GrandFathering
            15,  # Effetive FMV 31-03-2028 for long term assets
            12,  # Adj. FMV (lower of Sale & FMV)
            18,  # Adj. Cost of Acquisition (no indexation) (higher of Adj. FMV or Actual CoA)
            15,  # Capital Gain (w/o Indexation)
            15,  # Capital Gain (w/ Indexation)
            12,  # STCG (Rs.)
            12,  # LTCG w/o Indexation (Rs.)
            12,  # LTCG with Indexation (Rs.)
            12   # Status
        ]
        col_w_cm = {i: CM_IDEAL_WIDTHS[i] for i in range(ncols_cm)}
        # Numeric col indices for subtotal/grand total (only input data cols, not formula cols)
        CM_INPUT_NUM = {
            "Quantity", "Sale Price (Per unit)", "Sale Consideration (net)",
            "STT", "Gross Cost of Acquisition (w/o index)", "Indexed Cost of Acquisition",
            "FMV 31-Jan-2018 (per unit)", "FMV 31-Jan-2018 (Total)",
        }
        CM_FORMULA_COLS = {
            "Assets Eligible for GrandFathering",
            "Effetive FMV 31-03-2028 for long term assets",
            "Adj. FMV (lower of Sale & FMV)",
            "Adj. Cost of Acquisition (no indexation) (higher of Adj. FMV or Actual CoA)",
            "Capital Gain (w/o Indexation)",
            "Capital Gain (w/ Indexation)",
            "STCG (Rs.)", "LTCG w/o Indexation (Rs.)", "LTCG with Indexation (Rs.)",
        }
        CM_SUM_COLS = {
            "Quantity", "Sale Consideration (net)", "STT",
            "Gross Cost of Acquisition (w/o index)", "Indexed Cost of Acquisition",
            "FMV 31-Jan-2018 (Total)", "STCG (Rs.)",
            "LTCG w/o Indexation (Rs.)", "LTCG with Indexation (Rs.)"
        }
        cm_subtot_idx = sorted(i for i, c in enumerate(CM_COLS) if c in CM_SUM_COLS)

        # Column letter references (supports AA, AB etc.)
        def _cl(col_name):
            return _col_letter(CM_COLS.index(col_name))

        F_CM_GRP_HDR = _fmt(bold=True, size=10, color=WHITE, bg="#0E6674", align="center", wrap=True)
        F_CM_HDR     = _fmt(bold=True, size=10, color=WHITE, bg="#0E6674", align="center", wrap=True)
        F_CM_NUM_HDR = _fmt(bold=False, size=9, color=WHITE, bg="#0B535D", align="center")

        F_CM_SUB_LBL = _fmt(bold=True, color=WHITE, bg="#0E6674", align="left")
        F_CM_SUB_NUM = _fmt(bold=True, color=WHITE, bg="#0E6674",
                            align="right", num_fmt='#,##0.00;(#,##0.00);"-"')
        F_CM_SUB_QTY = _fmt(bold=True, color=WHITE, bg="#0E6674",
                            align="right", num_fmt='#,##0.00')
        F_CM_FORMULA = _fmt(bold=False, bg="#f5fff5", align="right", num_fmt='#,##0.00;(#,##0.00);"-"')
        F_AUDIT_HDR  = _fmt(bold=True, color=WHITE, bg=NAVY, align="left")
        F_AUDIT_NUM  = _fmt(bold=False, bg="#f9f9f9", align="right", num_fmt='#,##0.00;(#,##0.00);"-"')
        F_AUDIT_LBL  = _fmt(bold=False, bg="#f9f9f9", align="left")
        F_AUDIT_TOT_LBL = _fmt(bold=True, color=WHITE, bg=NAVY, align="left")
        F_AUDIT_TOT_NUM = _fmt(bold=True, color=WHITE, bg=NAVY,
                               align="right", num_fmt='#,##0.00;(#,##0.00);"-"')

        # Long term styling
        BLUE_TINT = "#f0f4ff"
        F_LT          = _fmt(bg=BLUE_TINT)
        F_LT_NUM      = _fmt(align="right", num_fmt='#,##0.00;(#,##0.00);"-"', bg=BLUE_TINT)
        F_LT_FORMULA  = _fmt(bg="#e6f2ff", align="right", num_fmt='#,##0.00;(#,##0.00);"-"')
        F_QTY         = _fmt(align="right", num_fmt='#,##0.00')
        F_LT_QTY      = _fmt(align="right", num_fmt='#,##0.00', bg=BLUE_TINT)

        ws_cm = wb.add_worksheet(CM_WS_NAME)
        ws_cm.set_tab_color(TC_SALE)
        ws_cm.hide_gridlines(2)
        _brand_row(ws_cm, ncols_cm)
        
        # Row 2 (index 1): Group Headers
        for c in range(ncols_cm):
            ws_cm.write_blank(1, c, None, F_CM_GRP_HDR)
        ws_cm.merge_range(1, 7, 1, 17, 'Security Transactions details', F_CM_GRP_HDR)
        ws_cm.merge_range(1, 18, 1, 23, 'Grandfathering u/s 55(2)(ac) [1961] or 90(7) [2025] for LTA accquired upto 31-1-2018', F_CM_GRP_HDR)
        ws_cm.merge_range(1, 24, 1, 28, 'Capital Gain Bifurcation', F_CM_GRP_HDR)
        ws_cm.set_row(1, 28)
        
        # Row 3 (index 2): Column Names
        for c, h in enumerate(CM_COLS):
            ws_cm.write(2, c, h, F_CM_HDR)
        ws_cm.set_row(2, 35)
        
        # Row 4 (index 3): Column Numbers (1 to 30)
        for c in range(ncols_cm):
            ws_cm.write(3, c, str(c + 1), F_CM_NUM_HDR)
        ws_cm.set_row(3, 18)

        ws_cm.freeze_panes(4, 0)   # freeze rows 1-4 only
        ws_cm.autofilter(3, 0, 3, ncols_cm - 1)

        row_cm = 4
        sr_cm = 1
        subtotal_rows_cm = []   # (sft_code, ind_sheet_name, subtotal_row)
        ind_sheet_row_counters = {}  # ind_name -> row index (starts at 3)

        def get_link_formulas(sft_code, ind_name, ind_row):
            sheet_esc = ind_name.replace("'", "''")
            formulas = {}
            
            formulas["SFT Code"] = sft_code
            formulas["Source"] = f"='{sheet_esc}'!B{ind_row}"
            formulas["TransID"] = f"='{sheet_esc}'!C{ind_row}"
            
            if "SFT-18" in sft_code:
                formulas["AMC Name (Code)"] = f"='{sheet_esc}'!D{ind_row}"
            else:
                formulas["AMC Name (Code)"] = ""
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Debit Type"] = f"='{sheet_esc}'!F{ind_row}"
            elif "SFT-17" in sft_code:
                formulas["Debit Type"] = f"='{sheet_esc}'!H{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Debit Type"] = f"='{sheet_esc}'!I{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Credit Type"] = ""
            elif "SFT-17" in sft_code:
                formulas["Credit Type"] = f"='{sheet_esc}'!I{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Credit Type"] = f"='{sheet_esc}'!J{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Date of Sale/Transfer"] = f"='{sheet_esc}'!E{ind_row}"
            elif "SFT-17" in sft_code:
                formulas["Date of Sale/Transfer"] = f"='{sheet_esc}'!D{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Date of Sale/Transfer"] = f"='{sheet_esc}'!E{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["ISIN"] = f"='{sheet_esc}'!G{ind_row}"
            elif "SFT-17" in sft_code:
                formulas["ISIN"] = f"='{sheet_esc}'!E{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["ISIN"] = f"='{sheet_esc}'!G{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Security Name"] = f"='{sheet_esc}'!H{ind_row}"
            elif "SFT-17" in sft_code:
                formulas["Security Name"] = f"='{sheet_esc}'!F{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Security Name"] = f"='{sheet_esc}'!H{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Security Class"] = f"='{sheet_esc}'!I{ind_row}"
            elif "SFT-17" in sft_code:
                formulas["Security Class"] = f"='{sheet_esc}'!G{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Security Class"] = f"='{sheet_esc}'!F{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Asset Type"] = ""
            elif "SFT-17" in sft_code:
                formulas["Asset Type"] = f"='{sheet_esc}'!J{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Asset Type"] = f"='{sheet_esc}'!K{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Quantity"] = f"='{sheet_esc}'!J{ind_row}"
            elif "SFT-17" in sft_code:
                formulas["Quantity"] = f"='{sheet_esc}'!K{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Quantity"] = f"='{sheet_esc}'!L{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Sale Price (Per unit)"] = f"='{sheet_esc}'!K{ind_row}"
            elif "SFT-17" in sft_code:
                formulas["Sale Price (Per unit)"] = f"='{sheet_esc}'!L{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Sale Price (Per unit)"] = f"='{sheet_esc}'!M{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Sale Consideration (net)"] = f"='{sheet_esc}'!M{ind_row}"
            elif "SFT-17" in sft_code:
                formulas["Sale Consideration (net)"] = f"='{sheet_esc}'!M{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Sale Consideration (net)"] = f"='{sheet_esc}'!N{ind_row}"
                
            if "SFT-18" in sft_code:
                formulas["STT"] = f"='{sheet_esc}'!O{ind_row}"
            else:
                formulas["STT"] = 0
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Gross Cost of Acquisition (w/o index)"] = 0
            elif "SFT-17" in sft_code:
                formulas["Gross Cost of Acquisition (w/o index)"] = f"='{sheet_esc}'!N{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Gross Cost of Acquisition (w/o index)"] = f"='{sheet_esc}'!P{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Indexed Cost of Acquisition"] = 0
            elif "SFT-17" in sft_code:
                formulas["Indexed Cost of Acquisition"] = f"='{sheet_esc}'!Q{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Indexed Cost of Acquisition"] = f"='{sheet_esc}'!S{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["FMV 31-Jan-2018 (per unit)"] = 0
            elif "SFT-17" in sft_code:
                formulas["FMV 31-Jan-2018 (per unit)"] = f"='{sheet_esc}'!O{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["FMV 31-Jan-2018 (per unit)"] = f"='{sheet_esc}'!Q{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["FMV 31-Jan-2018 (Total)"] = 0
            elif "SFT-17" in sft_code:
                formulas["FMV 31-Jan-2018 (Total)"] = f"='{sheet_esc}'!P{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["FMV 31-Jan-2018 (Total)"] = f"='{sheet_esc}'!R{ind_row}"
                
            if sft_code == "SFT-17-LES(OC)":
                formulas["Status"] = f"='{sheet_esc}'!N{ind_row}"
            elif "SFT-17" in sft_code:
                formulas["Status"] = f"='{sheet_esc}'!R{ind_row}"
            elif "SFT-18" in sft_code:
                formulas["Status"] = f"='{sheet_esc}'!T{ind_row}"
                
            return formulas

        for sft_code, ind_name, elems in cm_groups:
            group_start = row_cm
            defn = _SFT_SHEET_DEF.get(sft_code)
            if not defn:
                continue
            _, superset, num_set, col_rename = defn

            for elem in elems:
                l2 = _get_l2(elem)
                if not l2:
                    continue
                l1_cols, l1_rows = _get_l1(elem)
                l1_rows = _active_rows(l1_cols, l1_rows)
                if not l1_rows:
                    continue

                source = l2.get("source", "")
                l1_idx_map = {n: i for i, n in enumerate(l1_cols)}

                for data_row in l1_rows:
                    def _cv(col, _idx=l1_idx_map, _row=data_row, _ren=col_rename):
                        i = _idx.get(col)
                        if i is None and _ren:
                            for k, v in _ren.items():
                                if v == col:
                                    i = _idx.get(k)
                                    break
                        return _row[i] if i is not None and i < len(_row) else ""

                    # Resolve row counter for individual sheet
                    ind_row = ind_sheet_row_counters.get(ind_name, 3)
                    
                    # Get the cell-by-cell formulas
                    formulas = get_link_formulas(sft_code, ind_name, ind_row)
                    
                    # Highlight long term rows
                    asset_type = str(_cv("Asset Type") or "")
                    is_lt = "long" in asset_type.lower()
                    row_fmt = F_LT if is_lt else F_DEFAULT
                    num_fmt_to_use = F_LT_NUM if is_lt else F_NUM
                    formula_fmt_to_use = F_LT_FORMULA if is_lt else F_CM_FORMULA

                    # Write the 30 columns
                    for ci, col in enumerate(CM_COLS):
                        col_num_fmt = (F_LT_QTY if is_lt else F_QTY) if col == "Quantity" else num_fmt_to_use
                        if col == "Sr.":
                            ws_cm.write_number(row_cm, ci, sr_cm, row_fmt)
                        elif col in CM_FORMULA_COLS:
                            continue  # written below
                        else:
                            val = formulas.get(col, "")
                            if val == "" or val is None:
                                ws_cm.write_blank(row_cm, ci, None, row_fmt if col not in CM_INPUT_NUM else col_num_fmt)
                            elif col in CM_INPUT_NUM:
                                if isinstance(val, (int, float)):
                                    ws_cm.write_number(row_cm, ci, val, col_num_fmt)
                                elif val.startswith("="):
                                    ws_cm.write_formula(row_cm, ci, val, col_num_fmt)
                                else:
                                    ws_cm.write(row_cm, ci, val, col_num_fmt)
                            else:
                                if isinstance(val, (int, float)):
                                    ws_cm.write_number(row_cm, ci, val, row_fmt)
                                elif val.startswith("="):
                                    ws_cm.write_formula(row_cm, ci, val, row_fmt)
                                else:
                                    ws_cm.write(row_cm, ci, val, row_fmt)

                    # Excel row reference (1-based)
                    xr = xl_row(row_cm)
                    
                    # Grandfathering & Bifurcated gains formulas u/s 55(2)(ac)
                    ws_cm.write_formula(row_cm, CM_COLS.index("Assets Eligible for GrandFathering"),
                        f'=IF(AND(ISNUMBER(SEARCH("Long", L{xr})), OR(K{xr}="Listed Equity Share", K{xr}="Unit of Equity Oriented Mutual Fund", K{xr}="Unit of Business Trust", AND(K{xr}="Other Units", S{xr}>0))), "Yes - Eligible", IF(ISNUMBER(SEARCH("Short", L{xr})), "No - Short term Asset", "No - Ineligible Asset"))',
                        row_fmt)
                    
                    ws_cm.write_formula(row_cm, CM_COLS.index("Effetive FMV 31-03-2028 for long term assets"),
                        f'=IF(U{xr}="Yes - Eligible", T{xr}, 0)',
                        formula_fmt_to_use)
                    
                    ws_cm.write_formula(row_cm, CM_COLS.index("Adj. FMV (lower of Sale & FMV)"),
                        f'=MIN(O{xr}, V{xr})',
                        formula_fmt_to_use)
                    
                    ws_cm.write_formula(row_cm, CM_COLS.index("Adj. Cost of Acquisition (no indexation) (higher of Adj. FMV or Actual CoA)"),
                        f'=MAX(Q{xr}, W{xr})',
                        formula_fmt_to_use)
                    
                    ws_cm.write_formula(row_cm, CM_COLS.index("Capital Gain (w/o Indexation)"),
                        f'=O{xr}-X{xr}',
                        formula_fmt_to_use)
                    
                    ws_cm.write_formula(row_cm, CM_COLS.index("Capital Gain (w/ Indexation)"),
                        f'=O{xr}-R{xr}',
                        formula_fmt_to_use)
                    
                    ws_cm.write_formula(row_cm, CM_COLS.index("STCG (Rs.)"),
                        f'=IF(ISNUMBER(SEARCH("Short", L{xr})), Y{xr}, 0)',
                        formula_fmt_to_use)
                    
                    ws_cm.write_formula(row_cm, CM_COLS.index("LTCG w/o Indexation (Rs.)"),
                        f'=IF(ISNUMBER(SEARCH("Long", L{xr})), Y{xr}, 0)',
                        formula_fmt_to_use)
                    
                    ws_cm.write_formula(row_cm, CM_COLS.index("LTCG with Indexation (Rs.)"),
                        f'=IF(ISNUMBER(SEARCH("Long", L{xr})), Z{xr}, 0)',
                        formula_fmt_to_use)

                    # Update column widths for variables based on raw data value
                    for ci, col in enumerate(CM_COLS):
                        if col == "Sr.":
                            col_w_cm[ci] = max(col_w_cm.get(ci, 0), len(str(sr_cm)))
                        elif col in CM_FORMULA_COLS:
                            # computed columns are numbers/statuses; keep ideal base width
                            pass
                        else:
                            raw_val = _cv(col)
                            if raw_val is not None:
                                col_w_cm[ci] = max(col_w_cm.get(ci, 0), len(str(raw_val)))

                    sr_cm += 1
                    row_cm += 1
                    ind_sheet_row_counters[ind_name] = ind_row + 1

            group_end = row_cm - 1
            if group_start > group_end:
                continue

            for detail_row in range(group_start, group_end + 1):
                ws_cm.set_row(detail_row, None, None, {"level": 1})

            # Subtotal row — sums input + gain cols
            sub_lbl = f"Subtotal — {sft_code}"
            ws_cm.merge_range(row_cm, 0, row_cm, 11, sub_lbl, F_CM_SUB_LBL)
            for ci in cm_subtot_idx:
                cl = _col_letter(ci)
                col_name = CM_COLS[ci]
                is_qty = col_name == "Quantity"
                fmt = F_CM_SUB_QTY if is_qty else F_CM_SUB_NUM
                ws_cm.write_formula(row_cm, ci,
                    f"=SUM({cl}{xl_row(group_start)}:{cl}{xl_row(group_end)})",
                    fmt)
            for ci in range(ncols_cm):
                if ci < 12:
                    continue
                if ci not in cm_subtot_idx:
                    ws_cm.write_blank(row_cm, ci, None, F_CM_SUB_LBL)

            ws_cm.set_row(row_cm, 14)
            subtotal_rows_cm.append((sft_code, ind_name, row_cm))
            row_cm += 1

        # Grand total — sums subtotal rows only
        grand_lbl_cm = "GRAND TOTAL"
        ws_cm.merge_range(row_cm, 0, row_cm, 11, grand_lbl_cm, F_GRAND_LBL)
        for ci in cm_subtot_idx:
            cl = _col_letter(ci)
            col_name = CM_COLS[ci]
            is_qty = col_name == "Quantity"
            fmt = F_GRAND_QTY if is_qty else F_GRAND_NUM
            ws_cm.write_formula(row_cm, ci,
                "=" + "+".join(f"{cl}{xl_row(sr_row)}" for _, _, sr_row in subtotal_rows_cm),
                fmt)
        for ci in range(ncols_cm):
            if ci < 12:
                continue
            if ci not in cm_subtot_idx:
                ws_cm.write_blank(row_cm, ci, None, F_GRAND_LBL)
        ws_cm.set_row(row_cm, 15)
        row_cm += 1

        # Register defined names
        wb.define_name('CostWoIndex', f"='{CM_WS_NAME}'!$Q:$Q")
        wb.define_name('CostWIndex', f"='{CM_WS_NAME}'!$R:$R")
        wb.define_name('EligibleAssetForGF', f"='{CM_WS_NAME}'!$U:$U")
        wb.define_name('AdjustedFMV', f"='{CM_WS_NAME}'!$W:$W")
        wb.define_name('AdjustedCostWoIndex', f"='{CM_WS_NAME}'!$X:$X")
        wb.define_name('CapitalGainWoIndex', f"='{CM_WS_NAME}'!$Y:$Y")
        wb.define_name('CapitalGainWIndex', f"='{CM_WS_NAME}'!$Z:$Z")
        wb.define_name('STCG', f"='{CM_WS_NAME}'!$AA:$AA")
        wb.define_name('LTCGWoIndex', f"='{CM_WS_NAME}'!$AB:$AB")
        wb.define_name('LTCGWIndex', f"='{CM_WS_NAME}'!$AC:$AC")

        # ── Audit Trail ──
        # Two blank spacer rows
        row_cm += 2

        # Audit header
        AUDIT_COLS = ["SFT Code", "Individual Sheet", "Sales Consideration (Consolidated)",
                      "Sales Consideration (Individual Sheet)", "Difference", "Match?"]
        for ci, h in enumerate(AUDIT_COLS):
            ws_cm.write(row_cm, ci, h, F_AUDIT_HDR)
        ws_cm.set_row(row_cm, 14)
        row_cm += 1
        audit_start = row_cm

        sc_col_cm = CM_COLS.index("Sale Consideration (net)")
        sc_letter_cm = _col_letter(sc_col_cm)

        for sft_code, ind_name, sub_row in subtotal_rows_cm:
            # Sales Consideration from consolidated subtotal row
            consol_ref = f"{sc_letter_cm}{xl_row(sub_row)}"
            # Sales Consideration grand total from individual sheet grand total row
            ind_sheet_safe = ind_name.replace("'", "''")
            
            # Find the individual sheet definition to resolve the Sales Consideration column letter
            ind_defn = _SFT_SHEET_DEF.get(sft_code)
            ind_grand_row = _sheet_grand_row.get(ind_name)
            if ind_defn and ind_grand_row is not None:
                _, ind_sup, _, _ = ind_defn
                sc_col_ind = None
                for col_candidate in ["Sales Consideration", "Consideration", "End of the Day Value"]:
                    if col_candidate in ind_sup:
                        sc_col_ind = ind_sup.index(col_candidate) + 2  # +2 for Sr./Source
                        break
                if sc_col_ind is not None:
                    sc_letter_ind = chr(ord('A') + sc_col_ind)
                    ind_ref = f"='{ind_sheet_safe}'!{sc_letter_ind}{xl_row(ind_grand_row)}"
                    ws_cm.write(row_cm, 0, sft_code, F_AUDIT_LBL)
                    ws_cm.write(row_cm, 1, ind_name, F_AUDIT_LBL)
                    ws_cm.write_formula(row_cm, 2, f"={consol_ref}", F_AUDIT_NUM)
                    ws_cm.write_formula(row_cm, 3, ind_ref, F_AUDIT_NUM)
                    ws_cm.write_formula(row_cm, 4, f"=C{xl_row(row_cm)}-D{xl_row(row_cm)}", F_AUDIT_NUM)
                    ws_cm.write_formula(row_cm, 5,
                        f'=IF(ABS(C{xl_row(row_cm)}-D{xl_row(row_cm)})<0.01,"✓","✗")',
                        F_AUDIT_LBL)
                    col_w_cm[0] = max(col_w_cm.get(0, 0), len(sft_code))
                    col_w_cm[1] = max(col_w_cm.get(1, 0), len(ind_name))
                    row_cm += 1

        # Audit grand total row
        ws_cm.write(row_cm, 0, "GRAND TOTAL", F_AUDIT_TOT_LBL)
        ws_cm.write(row_cm, 1, "", F_AUDIT_TOT_LBL)
        ws_cm.write_formula(row_cm, 2,
            f"=SUM(C{xl_row(audit_start)}:C{xl_row(row_cm-1)})", F_AUDIT_TOT_NUM)
        ws_cm.write_formula(row_cm, 3,
            f"=SUM(D{xl_row(audit_start)}:D{xl_row(row_cm-1)})", F_AUDIT_TOT_NUM)
        ws_cm.write_formula(row_cm, 4,
            f"=C{xl_row(row_cm)}-D{xl_row(row_cm)}", F_AUDIT_TOT_NUM)
        ws_cm.write_formula(row_cm, 5,
            f'=IF(ABS(C{xl_row(row_cm)}-D{xl_row(row_cm)})<0.01,"✓","✗")',
            F_AUDIT_TOT_LBL)
        ws_cm.set_row(row_cm, 15)

        _autofit(ws_cm, [col_w_cm.get(i, 8) for i in range(ncols_cm)])

        # ── Plain-English Explanation Sheet ("ReadMe - Capital Gains") ──
        _log("Writing ReadMe - Capital Gains sheet…")
        ws_readme = wb.add_worksheet("ReadMe - Capital Gains")
        ws_readme.set_tab_color("#808080")
        ws_readme.hide_gridlines(2)
        
        # Title header: Merged A1:D1
        ws_readme.merge_range(0, 0, 0, 3, "Capital Gains Computation Guide (u/s 55(2)(ac))", F_AUDIT_HDR)
        ws_readme.set_row(0, 24)
        
        # Headers: Column, Field Name, Plain English Explanation, Tax Reference
        readme_headers = ["Column", "Field Name", "Plain English Explanation", "Tax Reference"]
        for ci, h in enumerate(readme_headers):
            ws_readme.write(2, ci, h, F_AUDIT_TOT_LBL)
        ws_readme.set_row(2, 18)
        
        # Table rows
        readme_rows = [
            ("Col U", "Assets Eligible for GrandFathering", 
             "Checks if the asset was purchased before 31-Jan-2018. Only Long Term Equity Shares, Equity Mutual Funds, and Business Trusts are eligible. Short-term assets are excluded.", 
             "Section 55(2)(ac)"),
            ("Col V", "Effective FMV", 
             "Holds the Fair Market Value (FMV) as of Jan 31, 2018 if the asset is eligible for grandfathering, otherwise zero.", 
             "Section 55(2)(ac)"),
            ("Col W", "Adj. FMV", 
             "Under tax rules, the grandfathered value cannot exceed what the asset actually sold for. This takes the lower of the actual sale value or the Jan 31, 2018 FMV.", 
             "Section 55(2)(ac)"),
            ("Col X", "Adj. Cost of Acquisition", 
             "The adjusted cost base used for long-term capital gain calculation. It is the higher of the actual purchase cost or the Adjusted FMV.", 
             "Section 55(2)(ac)"),
            ("Col Y", "Capital Gain (w/o Indexation)", 
             "The capital gain computed without adjusting for inflation. Calculated as: Sale Consideration - Adjusted Cost of Acquisition.", 
             "Section 112A / 111A"),
            ("Col Z", "Capital Gain (w/ Indexation)", 
             "The capital gain computed by adjusting the purchase cost for inflation using government Cost Inflation Indices. Calculated as: Sale Consideration - Indexed Cost of Acquisition. NOTE: Indexation benefits are abolished for transfers on or after 23-Jul-2024.", 
             "Section 112"),
            ("Col AA", "STCG (Rs.)", 
             "Short-Term Capital Gains. Applies if the asset was held for a short period (typically <= 12 months for equity, <= 24/36 months for others). Grandfathering and inflation adjustments do not apply.", 
             "Section 111A / Section 112"),
            ("Col AB", "LTCG w/o Indexation (Rs.)", 
             "Long-Term Capital Gains taxed at 10% (under Section 112A) without inflation indexation, utilizing the grandfathered cost base u/s 55(2)(ac). NOTE: For sales on or after 23-Jul-2024, the tax rate is 12.5% u/s 112A.", 
             "Section 112A"),
            ("Col AC", "LTCG with Indexation (Rs.)", 
             "Long-Term Capital Gains computed with inflation indexation. NOTE: Under the Finance Act 2024, indexation benefits are completely abolished for transfers executed on or after 23-Jul-2024. For such transactions, this value is not applicable.", 
             "Section 112"),
        ]
        
        # Formatting for table cells
        F_README_COL = _fmt(bold=True, align="center", border=1, bg="#f9f9f9")
        F_README_NAME = _fmt(bold=True, align="left", border=1, bg="#f9f9f9")
        F_README_TEXT = _fmt(align="left", wrap=True, border=1, bg="#f9f9f9")
        F_README_REF = _fmt(align="center", border=1, bg="#f9f9f9")
        
        row_idx = 3
        for col, name, desc, ref in readme_rows:
            ws_readme.write(row_idx, 0, col, F_README_COL)
            ws_readme.write(row_idx, 1, name, F_README_NAME)
            ws_readme.write(row_idx, 2, desc, F_README_TEXT)
            ws_readme.write(row_idx, 3, ref, F_README_REF)
            ws_readme.set_row(row_idx, 40)
            row_idx += 1
            
        row_idx += 2
        
        # Legal Disclaimer Block: styled with soft red fill (#F2DCDB) and dark red text
        F_DISCLAIMER = _fmt(bold=False, align="left", wrap=True, border=1, bg="#F2DCDB", color="#9C0006")
        disclaimer_text = (
            "Disclaimer: The computations, tax references, and plain-English explanations provided in this workbook "
            "are generated on a best-efforts basis for informational and illustrative purposes only. They do not constitute "
            "formal professional advice, legal opinion, or tax consulting. While every care has been taken to align the "
            "calculations with the provisions of the Income Tax Act, 1961 (including Section 55(2)(ac) and Section 112A/112), "
            "tax laws are subject to frequent legislative amendments, administrative updates, and varying judicial interpretations. "
            "The user is strongly advised to seek independent guidance from a qualified Chartered Accountant (CA) or tax "
            "professional and refer to the official statutory provisions/law before filing any tax returns or making investment decisions. "
            "The developers of this application assume no liability for any errors, omissions, or financial consequences arising "
            "from the use of this worksheet."
        )
        ws_readme.merge_range(row_idx, 0, row_idx + 4, 3, disclaimer_text, F_DISCLAIMER)
        ws_readme.set_row(row_idx, 20)
        ws_readme.set_row(row_idx + 1, 20)
        ws_readme.set_row(row_idx + 2, 20)
        ws_readme.set_row(row_idx + 3, 20)
        ws_readme.set_row(row_idx + 4, 20)
        
        # Column widths
        ws_readme.set_column(0, 0, 10)
        ws_readme.set_column(1, 1, 30)
        ws_readme.set_column(2, 2, 80)
        ws_readme.set_column(3, 3, 25)

    # ── Demand & Refund, Proceedings ─────────────────────────────────────
    _write_generic_section("Demand and Refund", sections.get("demandAndRefund"), TC_GENERAL)
    for sec in sections_list:
        title = sec.get("title", "")
        if "pending" in title.lower():
            _write_generic_section("Pending Proceedings", sec, TC_GENERAL)
        elif "complet" in title.lower():
            _write_generic_section("Completed Proceedings", sec, TC_GENERAL)

    # ── File properties ────────────────────────────────────────────────────
    wb.set_properties({
        "title":    f"AIS — {assessee_name} — FY {fy}",
        "subject":  f"Annual Information Statement | PAN: {pan} | FY: {fy}",
        "author":   "AayDoc Capio",
        "keywords": f"AIS, TDS, TCS, SFT, Capital Gains, {pan}, {fy}",
        "comments": f"Generated by AayDoc Capio on {report_ts}",
    })

    wb.close()
    return _safe_move(tmp_path, xlsx_path)


# ── Public API ─────────────────────────────────────────────────────────────────

def convert_ais_json(json_path: str, log_callback=None,
                     pan: str = None, dob: str = None) -> str:
    """
    Decrypt + parse an ITD AIS JSON file and write a structured Excel workbook.
    Returns the path to the xlsx file (alongside the source JSON).

    pan: PAN of the assessee (any case)
    dob: Date of birth in vault format DD-MM-YYYY
    """
    def _log(msg):
        if log_callback:
            log_callback(msg)

    _log(f"[AIS] Decrypting {os.path.basename(json_path)}…")
    data = decrypt_ais_json(json_path, pan, dob)

    meta = data.get("metadata", {})
    pan_in_file = meta.get("loggedInPan", pan or "")
    download_date = meta.get("downloadDate", "")

    # FY from JSON header ("Financial Year " label → "2024-25" value)
    hdr_labels = data.get("header", {}).get("columnLabel", [])
    hdr_values = data.get("header", {}).get("columnData", [])
    fy = ""
    for i, lab in enumerate(hdr_labels):
        if "Financial" in str(lab) and i < len(hdr_values):
            fy = str(hdr_values[i]).strip()
            break
    if not fy:
        fy = ais_derive_fy(download_date)  # fallback

    # Name is in partA columnData[2] (index of 'Name of Assessee')
    part_a_data = data.get("partA", {}).get("columnData", [])
    part_a_labels = data.get("partA", {}).get("columnLabel", [])
    try:
        name_idx = next(i for i, l in enumerate(part_a_labels) if "Name" in str(l))
        assessee_name = part_a_data[name_idx] if name_idx < len(part_a_data) else pan_in_file
    except StopIteration:
        assessee_name = pan_in_file

    # Determine output folders — if source is in a "Raw JSON" subfolder,
    # write decrypted JSON to sibling "Decrypted JSON/" and Excel to sibling "Excel/"
    # Otherwise write alongside the source file.
    import json as _json
    src_dir  = os.path.dirname(os.path.abspath(json_path))
    parent   = os.path.dirname(src_dir)

    if os.path.basename(src_dir) == "Raw JSON":
        dec_dir  = os.path.join(parent, "Decrypted JSON")
        xlsx_dir = os.path.join(parent, "Excel")
        os.makedirs(dec_dir,  exist_ok=True)
        os.makedirs(xlsx_dir, exist_ok=True)
    else:
        dec_dir  = src_dir
        xlsx_dir = src_dir

    fy_safe = fy.replace("-", "_")
    pan_out = (pan_in_file or "").upper()
    canonical_base = f"{pan_out}-AIS-{fy_safe}"
    dec_path  = os.path.join(dec_dir,  canonical_base + "_decrypted.json")
    xlsx_path = os.path.join(xlsx_dir, canonical_base + ".xlsx")

    with open(dec_path, "w", encoding="utf-8") as _f:
        _json.dump(data, _f, ensure_ascii=False, indent=2)
    _log(f"[AIS] Decrypted JSON saved: {dec_path}")
    _log(f"[AIS] Building Excel workbook for {assessee_name} — FY {fy}…")

    result_path = _write_ais_xlsx(
        data, xlsx_path, pan_in_file, fy, download_date, assessee_name, log_callback)

    _log(f"[AIS] Saved: {result_path}")
    return result_path
