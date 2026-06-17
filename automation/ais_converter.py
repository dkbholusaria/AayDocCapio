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

# Normalise varying purchase column names to a common label
_PURCHASE_COL_MAP = {
    "Market Purchase":      "Purchase Amount",
    "Total Purchase Amount":"Purchase Amount",
    "Market Sales":         "Sales Amount",
    "Total Sales Value":    "Sales Amount",
}

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
    NAVY   = "#0A1628"
    GREEN  = "#1a5c32"
    SUBTTL = "#d0e8c8"
    WHITE  = "#ffffff"
    GREY   = "#94A3B8"
    LABEL  = "#f0f4f0"
    GREEN_NUM = "#7fff8a"
    GREEN_TXT = "#1a3a22"

    def _fmt(bold=False, size=10, color="#000000", italic=False,
             bg=None, align="left", valign="vcenter", wrap=False,
             num_fmt=None, border=1, border_color="#D0D0D0", top_color=None):
        d = {
            "font_name": "Calibri", "font_size": size,
            "bold": bold, "italic": italic, "font_color": color,
            "align": align, "valign": valign, "text_wrap": wrap,
            "left": border, "right": border, "top": border, "bottom": border,
            "left_color": border_color, "right_color": border_color,
            "top_color": top_color or border_color, "bottom_color": border_color,
        }
        if bg:     d["bg_color"] = bg
        if num_fmt: d["num_format"] = num_fmt
        return wb.add_format(d)

    F_DEFAULT    = _fmt()
    F_NUM        = _fmt(align="right", num_fmt="#,##0.00")
    F_HDR        = _fmt(bold=True, color=WHITE, bg=GREEN, align="center")
    F_SUBTOT_LBL = _fmt(bold=True, color=GREEN_TXT, bg=SUBTTL, align="right",
                        top_color=GREEN)
    F_SUBTOT_NUM = _fmt(bold=True, color=GREEN_TXT, bg=SUBTTL, align="right",
                        num_fmt="#,##0.00", top_color=GREEN)
    F_GRAND_LBL  = _fmt(bold=True, color=WHITE, bg=NAVY, align="right")
    F_GRAND_NUM  = _fmt(bold=True, color=GREEN_NUM, bg=NAVY, align="right",
                        num_fmt="#,##0.00")
    F_BRAND_L    = _fmt(bold=True, size=10, color=WHITE, bg=NAVY, align="left")
    F_BRAND_R    = _fmt(size=8, color=GREY, bg=NAVY, align="right")
    F_LABEL      = _fmt(bold=True, bg=LABEL)
    F_VALUE      = _fmt()
    F_SECTION    = _fmt(bold=True, color=WHITE, bg=GREEN)

    report_ts = datetime.now().strftime("%d-%b-%Y %H:%M")

    def _brand_row(ws, ncols):
        left_text = f"AIS — {assessee_name} — {pan} — FY {fy}"
        right_text = f"AayDoc Capio™  ·  {report_ts}  ·  © 2026  ·  CA. Deepak Bhholusaria"
        split = min(3, ncols - 2)
        ws.merge_range(0, 0, 0, split, left_text, F_BRAND_L)
        if split + 1 <= ncols - 1:
            ws.merge_range(0, split + 1, 0, ncols - 1, right_text, F_BRAND_R)
        ws.set_row(0, 16)

    def _hdr_row(ws, cols, row=1):
        for c, h in enumerate(cols):
            ws.write(row, c, h, F_HDR)
        ws.set_row(row, 15)

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
                        ws.write_number(row_start, ci, amt, F_NUM)
                        totals[ci] = totals.get(ci, 0) + amt
                    else:
                        ws.write(row_start, ci, str(v) if v is not None else "", F_DEFAULT)
                    col_widths[ci] = max(col_widths.get(ci, 0), len(str(v)))
            row_start += 1
        return row_start, totals

    def _subtotal_row(ws, row, ncols, label, totals, col_widths):
        """Write a subtotal row after a group."""
        ws.write(row, 0, label, F_SUBTOT_LBL)
        for ci in range(1, ncols):
            if ci in totals:
                ws.write_number(row, ci, totals[ci], F_SUBTOT_NUM)
            else:
                ws.write_blank(row, ci, None, F_SUBTOT_LBL)
        ws.set_row(row, 14)
        col_widths[0] = max(col_widths.get(0, 0), len(label))

    def _grand_total_row(ws, row, ncols, grand_totals, col_widths):
        ws.write(row, 0, "Grand Total", F_GRAND_LBL)
        for ci in range(1, ncols):
            if ci in grand_totals:
                ws.write_number(row, ci, grand_totals[ci], F_GRAND_NUM)
            else:
                ws.write_blank(row, ci, None, F_GRAND_LBL)
        ws.set_row(row, 15)

    sections_list = data.get("partB", {}).get("sections", [])
    sections = {s["sectionKey"]: s for s in sections_list}

    header_labels = data.get("header", {}).get("columnLabel", [])
    header_values = data.get("header", {}).get("columnData", [])
    footer_labels  = data.get("footer", {}).get("columnLabel", [])
    footer_values  = data.get("footer", {}).get("columnData", [])

    # ── Sheet 1: General Info ──────────────────────────────────────────────
    _log("Writing General Info sheet…")
    ws_gi = wb.add_worksheet("General Info")
    ws_gi.hide_gridlines(2)
    ws_gi.set_column(0, 0, 28)
    ws_gi.set_column(1, 1, 52)
    ws_gi.merge_range(0, 0, 0, 1, f"AIS — {assessee_name} — {pan} — FY {fy}", F_BRAND_L)
    ws_gi.set_row(0, 16)

    row_gi = 1
    ws_gi.merge_range(row_gi, 0, row_gi, 1, "Part A — General Information", F_SECTION)
    ws_gi.set_row(row_gi, 16); row_gi += 1

    for lbl, val in zip(header_labels, header_values):
        ws_gi.write(row_gi, 0, lbl, F_LABEL)
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

    # ── Sheet 2: Summary ───────────────────────────────────────────────────
    _log("Writing Summary sheet…")
    SUMMARY_COLS = [
        "Section", "Info Category", "Info Code", "Description",
        "Source", "Count", "Amount",
    ]
    ws_sum = wb.add_worksheet("Summary")
    ws_sum.hide_gridlines(2)
    _brand_row(ws_sum, len(SUMMARY_COLS))
    _hdr_row(ws_sum, SUMMARY_COLS)

    row_s = 2
    col_w = {i: len(h) for i, h in enumerate(SUMMARY_COLS)}
    sec_labels = {
        "tdsTcs": "B1 — TDS/TCS",
        "sft": "B2 — SFT",
        "paymentOfTaxes": "B3 — Payment of Taxes",
        "demandAndRefund": "B4 — Demand & Refund",
        "other-info": "B7 — Other Info",
    }
    grand_amt = 0.0
    for sec in sections_list:
        sec_key = sec.get("sectionKey", "")
        sec_label = sec_labels.get(sec_key, sec_key)
        for elem in sec.get("elements", []):
            l2 = _get_l2(elem)
            if not l2:
                continue
            l2_amt = _parse_amount(l2.get("amount", "")) or 0.0
            grand_amt += l2_amt
            # SUMMARY_COLS: Section | Info Category | Info Code | Description | Source | Count | Amount
            vals = [
                sec_label,
                l2.get("category", ""),
                l2.get("info_code", ""),
                l2.get("description", ""),
                l2.get("source", ""),
                l2.get("count", ""),
            ]
            for ci, v in enumerate(vals):
                ws_sum.write(row_s, ci, str(v) if v is not None else "", F_DEFAULT)
                col_w[ci] = max(col_w.get(ci, 0), len(str(v)))
            ws_sum.write_number(row_s, 6, l2_amt, F_NUM)
            col_w[6] = max(col_w.get(6, 0), len(f"{l2_amt:,.2f}"))
            row_s += 1

    ws_sum.write(row_s, 0, "Grand Total", F_GRAND_LBL)
    for ci in range(1, 6):
        ws_sum.write_blank(row_s, ci, None, F_GRAND_LBL)
    ws_sum.write_number(row_s, 6, grand_amt, F_GRAND_NUM)
    ws_sum.set_row(row_s, 15)
    _autofit(ws_sum, [col_w.get(i, 8) for i in range(7)])

    # ── Sheet 3: TDS / TCS ────────────────────────────────────────────────
    tds_sec = sections.get("tdsTcs")
    tds_elems = (tds_sec or {}).get("elements", [])
    if tds_elems:
        _log("Writing TDS/TCS sheet…")
        # Uniform 8-col l1; prepend Info Code + Description + Source
        TDS_PREFIX = ["Info Code", "Description", "Source"]
        TDS_L1 = ["TSN", "Quarter", "Date of Payment/Credit",
                   "Amount Paid/Credited", "TDS Deducted", "TDS Deposited",
                   "Status"]
        TDS_NUM = {"Amount Paid/Credited", "TDS Deducted", "TDS Deposited"}
        TDS_COLS = TDS_PREFIX + TDS_L1
        ncols = len(TDS_COLS)

        ws_tds = wb.add_worksheet("TDS - TCS")
        ws_tds.hide_gridlines(2)
        _brand_row(ws_tds, ncols)
        _hdr_row(ws_tds, TDS_COLS)

        row_t = 2
        col_w = {i: len(h) for i, h in enumerate(TDS_COLS)}
        grand = {}

        for elem in tds_elems:
            l2 = _get_l2(elem)
            if not l2:
                continue
            l1_cols, l1_rows = _get_l1(elem)
            if not l1_rows:
                continue
            prefix = [l2["info_code"], l2["description"], l2["source"]]
            row_t, totals = _write_group(
                ws_tds, row_t, prefix, l1_cols, l1_rows,
                TDS_L1, None, TDS_NUM, col_w)
            for k, v in totals.items():
                grand[k] = grand.get(k, 0) + v
            lbl = f"Subtotal — {l2['source'][:40]}"
            _subtotal_row(ws_tds, row_t, ncols, lbl, totals, col_w)
            row_t += 1

        _grand_total_row(ws_tds, row_t, ncols, grand, col_w)
        _autofit(ws_tds, [col_w.get(i, 8) for i in range(ncols)])

    # ── SFT classification ─────────────────────────────────────────────────
    sft_sec = sections.get("sft")
    sft_elems = (sft_sec or {}).get("elements", [])
    sft_sales, sft_pur, sft_other = [], [], []

    for elem in sft_elems:
        l1src = (elem.get("l1Src") or "").strip()
        l2 = _get_l2(elem)
        code = l2.get("info_code", "")
        if l1src == _SALES_L1SRC:
            sft_sales.append(elem)
        elif l1src == _PURCHASE_L1SRC and "Div" not in code:
            sft_pur.append(elem)
        else:
            sft_other.append(elem)

    # ── Sheet 4: Capital Market Sales ─────────────────────────────────────
    if sft_sales:
        _log("Writing Capital Market Sales sheet…")
        SALES_PREFIX = ["Info Code", "Source"]
        SALES_COLS = SALES_PREFIX + _SALES_SUPERSET
        SALES_NUM = {"Quantity", "Sale Price Per unit", "Sales Consideration",
                     "STT", "Cost of Acquisition", "Unit FMV",
                     "Fair Market Value", "Indexed Cost of Acquisition"}
        ncols = len(SALES_COLS)

        ws_sales = wb.add_worksheet("Capital Market Sales")
        ws_sales.hide_gridlines(2)
        _brand_row(ws_sales, ncols)
        _hdr_row(ws_sales, SALES_COLS)

        row_s2 = 2
        col_w = {i: len(h) for i, h in enumerate(SALES_COLS)}
        grand = {}

        for elem in sft_sales:
            l2 = _get_l2(elem)
            if not l2:
                continue
            l1_cols, l1_rows = _get_l1(elem)
            if not l1_rows:
                continue
            prefix = [l2["info_code"], l2["source"]]
            row_s2, totals = _write_group(
                ws_sales, row_s2, prefix, l1_cols, l1_rows,
                _SALES_SUPERSET, None, SALES_NUM, col_w)
            for k, v in totals.items():
                grand[k] = grand.get(k, 0) + v
            lbl = f"Subtotal — {l2['info_code']}  [{l2['source'][:30]}]"
            _subtotal_row(ws_sales, row_s2, ncols, lbl, totals, col_w)
            row_s2 += 1

        _grand_total_row(ws_sales, row_s2, ncols, grand, col_w)
        _autofit(ws_sales, [col_w.get(i, 8) for i in range(ncols)])

    # ── Sheet 5: Capital Market Purchases ─────────────────────────────────
    if sft_pur:
        _log("Writing Capital Market Purchases sheet…")
        PUR_PREFIX = ["Info Code", "Source"]
        PUR_COLS = PUR_PREFIX + _PURCHASES_SUPERSET
        PUR_NUM = {"Purchase Amount", "Sales Amount"}
        ncols = len(PUR_COLS)

        ws_pur = wb.add_worksheet("Capital Market Purchases")
        ws_pur.hide_gridlines(2)
        _brand_row(ws_pur, ncols)
        _hdr_row(ws_pur, PUR_COLS)

        row_p = 2
        col_w = {i: len(h) for i, h in enumerate(PUR_COLS)}
        grand = {}

        for elem in sft_pur:
            l2 = _get_l2(elem)
            if not l2:
                continue
            l1_cols, l1_rows = _get_l1(elem)
            if not l1_rows:
                continue
            prefix = [l2["info_code"], l2["source"]]
            row_p, totals = _write_group(
                ws_pur, row_p, prefix, l1_cols, l1_rows,
                _PURCHASES_SUPERSET, _PURCHASE_COL_MAP, PUR_NUM, col_w)
            for k, v in totals.items():
                grand[k] = grand.get(k, 0) + v
            lbl = f"Subtotal — {l2['info_code']}  [{l2['source'][:30]}]"
            _subtotal_row(ws_pur, row_p, ncols, lbl, totals, col_w)
            row_p += 1

        _grand_total_row(ws_pur, row_p, ncols, grand, col_w)
        _autofit(ws_pur, [col_w.get(i, 8) for i in range(ncols)])

    # ── Sheet 6: SFT — Other ──────────────────────────────────────────────
    if sft_other:
        _log("Writing SFT — Other sheet…")
        # Dynamic superset — scan all elements first
        dyn_sup = _build_dynamic_superset(sft_other)
        OTHER_PREFIX = ["Info Code", "Description", "Source"]
        OTHER_COLS = OTHER_PREFIX + dyn_sup
        OTHER_NUM_KEYWORDS = {"amount", "value", "consideration", "price",
                               "dividend", "interest", "payment"}
        OTHER_NUM = {c for c in dyn_sup
                     if any(k in c.lower() for k in OTHER_NUM_KEYWORDS)}
        ncols = len(OTHER_COLS)

        ws_oth = wb.add_worksheet("SFT - Other")
        ws_oth.hide_gridlines(2)
        _brand_row(ws_oth, ncols)
        _hdr_row(ws_oth, OTHER_COLS)

        row_o = 2
        col_w = {i: len(h) for i, h in enumerate(OTHER_COLS)}
        grand = {}

        for elem in sft_other:
            l2 = _get_l2(elem)
            if not l2:
                continue
            l1_cols, l1_rows = _get_l1(elem)
            if not l1_rows:
                continue
            prefix = [l2["info_code"], l2["description"], l2["source"]]
            row_o, totals = _write_group(
                ws_oth, row_o, prefix, l1_cols, l1_rows,
                dyn_sup, None, OTHER_NUM, col_w)
            for k, v in totals.items():
                grand[k] = grand.get(k, 0) + v
            lbl = f"Subtotal — {l2['info_code']}  [{l2['source'][:30]}]"
            _subtotal_row(ws_oth, row_o, ncols, lbl, totals, col_w)
            row_o += 1

        _grand_total_row(ws_oth, row_o, ncols, grand, col_w)
        _autofit(ws_oth, [col_w.get(i, 8) for i in range(ncols)])

    # ── Sheet 7: Payment of Taxes ─────────────────────────────────────────
    tax_sec = sections.get("paymentOfTaxes")
    tax_elems = (tax_sec or {}).get("elements", [])
    # direct schema: each element has columnLabel (list of str) + columnData
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
        ws_tax.hide_gridlines(2)
        _brand_row(ws_tax, ncols)
        _hdr_row(ws_tax, tax_cols)

        row_tx = 2
        col_w = {i: len(h) for i, h in enumerate(tax_cols)}
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

        _grand_total_row(ws_tax, row_tx, ncols, grand, col_w)
        _autofit(ws_tax, [col_w.get(i, 8) for i in range(ncols)])

    # ── Generic flat-table writer for B7, B4, B5, B6 ─────────────────────
    def _write_generic_section(ws_name: str, section: dict | None):
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
        ws.hide_gridlines(2)
        _brand_row(ws, ncols)
        _hdr_row(ws, COLS)

        row_g = 2
        col_w = {i: len(h) for i, h in enumerate(COLS)}
        grand = {}

        for elem in elems:
            l2 = _get_l2(elem)
            l1_cols, l1_rows = _get_l1(elem)
            prefix = [l2.get("info_code",""), l2.get("description",""), l2.get("source","")]
            row_g, totals = _write_group(
                ws, row_g, prefix, l1_cols, l1_rows, dyn_sup, None, NUM_COLS, col_w)
            for k, v in totals.items():
                grand[k] = grand.get(k, 0) + v
            if l1_rows:
                src = l2.get("source","")[:30]
                lbl = f"Subtotal — {l2.get('info_code','')}  [{src}]"
                _subtotal_row(ws, row_g, ncols, lbl, totals, col_w)
                row_g += 1

        if grand:
            _grand_total_row(ws, row_g, ncols, grand, col_w)
        _autofit(ws, [col_w.get(i, 8) for i in range(ncols)])

    # ── Sheet 8: B7 / Other Info ──────────────────────────────────────────
    _write_generic_section("B7 - Other Info", sections.get("other-info"))

    # ── Sheet 9: Demand & Refund ──────────────────────────────────────────
    _write_generic_section("Demand and Refund", sections.get("demandAndRefund"))

    # ── Sheets 10-11: B5 / B6 proceedings (if present) ───────────────────
    for sec in sections_list:
        title = sec.get("title", "")
        if "pending" in title.lower():
            _write_generic_section("Pending Proceedings", sec)
        elif "complet" in title.lower():
            _write_generic_section("Completed Proceedings", sec)

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
    fy = ais_derive_fy(download_date)

    header_values = data.get("header", {}).get("columnData", [])
    assessee_name = header_values[2] if len(header_values) > 2 else pan_in_file

    xlsx_path = os.path.splitext(json_path)[0] + ".xlsx"
    _log(f"[AIS] Building Excel workbook for {assessee_name} — FY {fy}…")

    result_path = _write_ais_xlsx(
        data, xlsx_path, pan_in_file, fy, download_date, assessee_name, log_callback)

    _log(f"[AIS] Saved: {result_path}")
    return result_path
