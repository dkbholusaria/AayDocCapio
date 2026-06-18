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

    _DISPLAY_RENAME = {"TSN": "TransID"}

    def _hdr_row(ws, cols, row=1):
        for c, h in enumerate(cols):
            ws.write(row, c, _DISPLAY_RENAME.get(h, h), F_HDR)
        ws.set_row(row, 15)
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
        "Source", "Amount",
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
            vals = [
                sec_label,
                l2.get("category", ""),
                l2.get("info_code", ""),
                l2.get("description", ""),
                l2.get("source", ""),
            ]
            for ci, v in enumerate(vals):
                ws_sum.write(row_s, ci, str(v) if v is not None else "", F_DEFAULT)
                col_w[ci] = max(col_w.get(ci, 0), len(str(v)))
            ws_sum.write_number(row_s, 5, l2_amt, F_NUM)
            col_w[5] = max(col_w.get(5, 0), len(f"{l2_amt:,.2f}"))
            row_s += 1

    ws_sum.write(row_s, 0, "Grand Total", F_GRAND_LBL)
    for ci in range(1, 5):
        ws_sum.write_blank(row_s, ci, None, F_GRAND_LBL)
    ws_sum.write_number(row_s, 5, grand_amt, F_GRAND_NUM)
    ws_sum.set_row(row_s, 15)
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
        col_w = {i: len(h) for i, h in enumerate(cols)}
        subtotal_rows = []
        sr = 0

        for elem in elems:
            l2 = _get_l2(elem)
            if not l2:
                continue
            l1_cols, l1_rows = _get_l1(elem)
            l1_rows = _active_rows(l1_cols, l1_rows)
            if not l1_rows:
                continue

            name, tan = _split_source(l2.get("source", ""))
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
            info_code   = l2.get("info_code", "")
            description = l2.get("description", "")
            ws.write(row, 0, sr,            F_DEFAULT)
            ws.write(row, 1, name,          F_DEFAULT)
            ws.write(row, 2, tan,           F_DEFAULT)
            ws.write(row, 3, info_code,     F_DEFAULT)
            ws.write(row, 4, description,   F_DEFAULT)
            ws.write(row, 5, _c("TSN"),                    F_DEFAULT)
            ws.write(row, 6, _c("Quarter"),                F_DEFAULT)
            ws.write(row, 7, _c("Date of Payment/Credit"), F_DEFAULT)
            for ci, col in [(8, "Amount Paid/Credited"), (9, "TDS Deducted"), (10, "TDS Deposited")]:
                amt = _parse_amount(str(_c(col)))
                ws.write_number(row, ci, amt if amt is not None else 0, F_NUM)
            ws.write(row, 11, _c("Status"), F_DEFAULT)
            for ci, v in enumerate([sr, name, tan, info_code, description,
                                     _c("TSN"), _c("Quarter"), _c("Date of Payment/Credit")]):
                col_w[ci] = max(col_w.get(ci, 0), len(str(v)))

        ws_tds = wb.add_worksheet("Part B1 - TDS TCS")
        _write_tds_sheet(ws_tds, tds_standard, STD_COLS, STD_NUM,
                         "GRAND TOTAL — Part B1 · TDS & TCS",
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

        ws_prop = wb.add_worksheet("Part B1 - TDS on Property")
        _write_tds_sheet(ws_prop, tds_property, PROP_COLS, PROP_NUM,
                         "GRAND TOTAL — Part B1 · TDS on Property (194IA)",
                         _prop_row, label_merge_end=7)

    # ── SFT — one sheet per info_code ─────────────────────────────────────
    sft_sec = sections.get("sft")
    sft_elems = (sft_sec or {}).get("elements", [])

    # Group elements by info_code, preserving order of first appearance
    sft_by_code: dict[str, list] = {}
    for elem in sft_elems:
        l2 = _get_l2(elem)
        code = l2.get("info_code", "")
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
        "SFT-005":        ("B2 - SFT-005 Time Deposit",        _SFT_PRSN_BASE,    _SFT_PRSN_NUM,   None),
        "SFT-006":        ("B2 - SFT-006 Credit Card",         _SFT_006_COLS,     _SFT_006_NUM,    None),
        "SFT-008":        ("B2 - SFT-008 Purchase of Shares",  _SFT_PRSN_BASE,    _SFT_PRSN_NUM,   None),
        "SFT-010":        ("B2 - SFT-010 MF Purchase",         _SFT_PRSN_BASE,    _SFT_PRSN_NUM,   None),
        "SFT-012":        ("B2 - SFT-012 Immovable Property",  _SFT_012_COLS,     _SFT_012_NUM,    None),
        "SFT-015":        ("B2 - SFT-015 Dividend",            _SFT_015_COLS,     _SFT_015_NUM,    None),
        "SFT-016(SB)":    ("B2 - SFT-016 Interest Savings",    _SFT_016_COLS,     _SFT_016_NUM,    None),
        "SFT-016(TD)":    ("B2 - SFT-016 Interest Term Dep",   _SFT_016_COLS,     _SFT_016_NUM,    None),
        "SFT-016(RD)":    ("B2 - SFT-016 Interest Rec Dep",    _SFT_016_COLS,     _SFT_016_NUM,    None),
        "SFT-17(Pur)":    ("B2 - SFT-17 Sec Purchase Dep",     _SFT_17PUR_COLS,   _SFT_17PUR_NUM,  None),
        "SFT-18(Pur)":    ("B2 - SFT-18 MF Purchase RTA",      _SFT_18PUR_COLS,   _SFT_18PUR_NUM,  _PURCHASE_COL_MAP),
        "SFT-18(Div)":    ("B2 - SFT-18 MF Dividend RTA",      _SFT_18DIV_COLS,   _SFT_18DIV_NUM,  None),
        "SFT-17-LES(M)":  ("B2 - SFT-17 Equity Sale Dep",      _SFT_17M_SUPERSET, _SFT_17M_NUM,    None),
        "SFT-17-LDB(M)":  ("B2 - SFT-17 Debenture Sale Dep",   _SFT_17M_SUPERSET, _SFT_17M_NUM,    None),
        "SFT-17-EMF(M)":  ("B2 - SFT-17 Eq MF Sale Dep",       _SFT_17M_SUPERSET, _SFT_17M_NUM,    None),
        "SFT-17-UBT(M)":  ("B2 - SFT-17 Bus Trust Sale Dep",   _SFT_17M_SUPERSET, _SFT_17M_NUM,    None),
        "SFT-17-OTU(M)":  ("B2 - SFT-17 Othr Units Sale Dep",  _SFT_17M_SUPERSET, _SFT_17M_NUM,    None),
        "SFT-17-LES(OC)": ("B2 - SFT-17 Equity Off-Market",    _SFT_17OC_COLS,    _SFT_17OC_NUM,   None),
        "SFT-18-EMF(M)":  ("B2 - SFT-18 Eq MF Sale RTA",       _SFT_18M_SUPERSET, _SFT_18M_NUM,    None),
        "SFT-18-OTU(M)":  ("B2 - SFT-18 Othr Units Sale RTA",  _SFT_18M_SUPERSET, _SFT_18M_NUM,    None),
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
        col_w = {i: len(h) for i, h in enumerate(full_cols)}
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
            if not l2:
                continue
            l1_cols, l1_rows = _get_l1(elem)
            l1_rows = _active_rows(l1_cols, l1_rows)
            if not l1_rows:
                continue

            source = l2.get("source", "")
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
        col_w = {i: len(h) for i, h in enumerate(full_cols)}
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
            if not l2:
                continue
            l1_cols, l1_rows = _get_l1(elem)
            l1_rows = _active_rows(l1_cols, l1_rows)
            if not l1_rows:
                continue

            source = l2.get("source", "")
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
            ws.write_formula(row, ci,
                f"=SUM({col_letter}{xl_row(detail_start)}:{col_letter}{xl_row(detail_end)})",
                F_GRAND_NUM)
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
        wb.get_worksheet_by_name("Part B1 - TDS TCS").set_tab_color(TC_TAX)
    if tds_property:
        wb.get_worksheet_by_name("Part B1 - TDS on Property").set_tab_color(TC_TAX)

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
        col_w = {i: len(h) for i, h in enumerate(COLS)}
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
                _subtotal_row(ws, row_g, ncols, lbl, totals, col_w)
                row_g += 1

        if grand:
            _grand_total_row(ws, row_g, ncols, grand, col_w)
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
            _log("Writing B7 - Salary (TDS Annexure II) sheet…")
            _write_sft_sheet("B7 - Salary", elems, SAL_SUPERSET, SAL_NUM, None)
            ws = wb.get_worksheet_by_name("B7 - Salary")
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
        "SFT Code", "Sr.", "Source", "TSN",
        "AMC Name (Code)", "Date of Sale/Transfer", "ISIN", "Security Name",
        "Security Class", "Debit Type", "Credit Type", "Asset Type",
        "Quantity", "Sale Price Per unit",
        "Gross Sale Consideration", "STT", "Gross Cost of Acquisition",
        "FMV 31-Jan-2018 (per unit)", "Total FMV u/s 55(2)(ac)",
        "Adj. FMV (lower of Sale & FMV)", "Adj. Cost (no indexation)",
        "Cost with Indexation", "Indexed Cost of Acquisition",
        "Transfer Expenditure",
        "STCG (Rs.)", "LTCG w/o Indexation (Rs.)", "LTCG with Indexation (Rs.)",
        "Tax @10%", "Status",
    ]
    # Column letter helper (0-based index → Excel letter, supports AA etc.)
    def _col_letter(idx):
        if idx < 26:
            return chr(ord('A') + idx)
        return chr(ord('A') + idx // 26 - 1) + chr(ord('A') + idx % 26)
    # (sft_code, individual_sheet_name)
    CM_SOURCES = [
        ("SFT-17-LES(M)",  "B2 - SFT-17 Equity Sale Dep"),
        ("SFT-17-LDB(M)",  "B2 - SFT-17 Debenture Sale Dep"),
        ("SFT-17-EMF(M)",  "B2 - SFT-17 Eq MF Sale Dep"),
        ("SFT-17-UBT(M)",  "B2 - SFT-17 Bus Trust Sale Dep"),
        ("SFT-17-OTU(M)",  "B2 - SFT-17 Othr Units Sale Dep"),
        ("SFT-17-LES(OC)", "B2 - SFT-17 Equity Off-Market"),
        ("SFT-18-EMF(M)",  "B2 - SFT-18 Eq MF Sale RTA"),
        ("SFT-18-OTU(M)",  "B2 - SFT-18 Othr Units Sale RTA"),
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
        _log("Writing Capital Market — Consolidated sheet…")
        CM_WS_NAME = "Capital Market — Consolidated"
        ncols_cm = len(CM_COLS)
        col_w_cm = {i: len(h) for i, h in enumerate(CM_COLS)}
        # Numeric col indices for subtotal/grand total (only input data cols, not formula cols)
        CM_INPUT_NUM = {
            "Quantity", "Sale Price Per unit",
            "Gross Sale Consideration", "STT", "Gross Cost of Acquisition",
            "FMV 31-Jan-2018 (per unit)", "Indexed Cost of Acquisition",
            "Transfer Expenditure",
        }
        CM_FORMULA_COLS = {
            "Adj. FMV (lower of Sale & FMV)",
            "Adj. Cost (no indexation)", "Cost with Indexation",
            "STCG (Rs.)", "LTCG w/o Indexation (Rs.)", "LTCG with Indexation (Rs.)",
            "Tax @10%",
        }
        # Total FMV is now a direct value from JSON, so add to input num set
        CM_INPUT_NUM_EXT = CM_INPUT_NUM | {"Total FMV u/s 55(2)(ac)"}
        cm_num_idx = sorted(i for i, c in enumerate(CM_COLS) if c in CM_INPUT_NUM_EXT)
        cm_subtot_idx = sorted(i for i, c in enumerate(CM_COLS)
                               if c in CM_INPUT_NUM_EXT | {"STCG (Rs.)", "LTCG w/o Indexation (Rs.)",
                                                            "LTCG with Indexation (Rs.)"})

        # Column letter references (supports AA, AB etc.)
        def _cl(col_name):
            return _col_letter(CM_COLS.index(col_name))

        F_CM_SUB_LBL = _fmt(bold=True, color=WHITE, bg="#0E6674", align="left")
        F_CM_SUB_NUM = _fmt(bold=True, color=WHITE, bg="#0E6674",
                            align="right", num_fmt="#,##0.00")
        F_CM_FORMULA = _fmt(bold=False, bg="#f5fff5", align="right", num_fmt="#,##0.00")
        F_AUDIT_HDR  = _fmt(bold=True, color=WHITE, bg=NAVY, align="left")
        F_AUDIT_NUM  = _fmt(bold=False, bg="#f9f9f9", align="right", num_fmt="#,##0.00")
        F_AUDIT_LBL  = _fmt(bold=False, bg="#f9f9f9", align="left")
        F_AUDIT_TOT_LBL = _fmt(bold=True, color=WHITE, bg=NAVY, align="left")
        F_AUDIT_TOT_NUM = _fmt(bold=True, color=WHITE, bg=NAVY,
                               align="right", num_fmt="#,##0.00")

        ws_cm = wb.add_worksheet(CM_WS_NAME)
        ws_cm.set_tab_color(TC_SALE)
        ws_cm.hide_gridlines(2)
        _brand_row(ws_cm, ncols_cm)
        _hdr_row(ws_cm, CM_COLS)
        ws_cm.freeze_panes(2, 6)   # freeze up to ISIN column

        row_cm = 2
        subtotal_rows_cm = []   # (sft_code, ind_sheet_name, subtotal_row)

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

                    raw_vals = [data_row[l1_idx_map[c]] if c in l1_idx_map and l1_idx_map[c] < len(data_row) else ""
                                for c in l1_cols]
                    mapped = _map_to_superset(raw_vals, l1_cols, superset, col_rename)
                    sup_idx = {c: i for i, c in enumerate(superset)}

                    def _sv(col_name):
                        i = sup_idx.get(col_name)
                        return mapped[i] if i is not None else ""

                    # ISIN split
                    sec_raw = _cv("Security Name (Security Code)")
                    isin, secname = _split_security_name(str(sec_raw)) if sec_raw else ("", "")
                    if not isin:
                        isin    = str(_sv("ISIN"))
                        secname = str(_sv("Security Name"))

                    # Direct data values
                    direct = {
                        "SFT Code":                  sft_code,
                        "Sr.":                       "",
                        "Source":                    source,
                        "TSN":                       str(_sv("TSN") or ""),
                        "AMC Name (Code)":           str(_sv("AMC Name (Code)") or ""),
                        "Date of Sale/Transfer":     str(_sv("Date of Sale/Transfer") or _cv("Date of Transfer") or ""),
                        "ISIN":                      isin,
                        "Security Name":             secname,
                        "Security Class":            str(_sv("Security Class") or ""),
                        "Debit Type":                str(_sv("Debit Type") or _sv("Nature of Transfer") or ""),
                        "Credit Type":               str(_sv("Credit Type") or ""),
                        "Asset Type":                str(_sv("Asset Type") or ""),
                        "Quantity":                  _sv("Quantity") or _sv("Quantity Transferred") or "",
                        "Sale Price Per unit":       _sv("Sale Price Per unit") or _sv("EOD Price per Unit") or "",
                        "Gross Sale Consideration":  _sv("Sales Consideration") or _sv("Consideration") or _sv("End of the Day Value") or "",
                        "STT":                       _sv("STT") or "",
                        "Gross Cost of Acquisition": _sv("Cost of Acquisition") or "",
                        # Unit FMV = FMV per unit as of 31-Jan-2018 for grandfathering
                        "FMV 31-Jan-2018 (per unit)": _sv("Unit FMV") or "",
                        # Total FMV u/s 55(2)(ac) = Fair Market Value (already computed in JSON as Qty × Unit FMV)
                        "Total FMV u/s 55(2)(ac)":   _sv("Fair Market Value") or "",
                        # Indexed Cost of Acquisition — directly from JSON (non-zero for LT indexed assets)
                        "Indexed Cost of Acquisition": _sv("Indexed Cost of Acquisition") or "",
                        "Transfer Expenditure":      "",
                        "Status":                    str(_sv("Status") or "Active"),
                    }

                    # Write direct columns first
                    for ci, col in enumerate(CM_COLS):
                        if col in CM_FORMULA_COLS:
                            continue  # written as formulas below
                        val = direct.get(col, "")
                        if col in CM_INPUT_NUM_EXT:
                            amt = _parse_amount(str(val)) if val != "" else None
                            ws_cm.write_number(row_cm, ci, amt if amt is not None else 0, F_NUM)
                        else:
                            ws_cm.write(row_cm, ci, str(val) if val is not None else "", F_DEFAULT)

                    # Excel row reference (1-based)
                    xr = xl_row(row_cm)
                    O = _cl("Gross Sale Consideration")
                    Q = _cl("Gross Cost of Acquisition")
                    S = _cl("Total FMV u/s 55(2)(ac)")   # direct from JSON (Fair Market Value)
                    W = _cl("Indexed Cost of Acquisition")
                    X = _cl("Transfer Expenditure")
                    L = _cl("Asset Type")
                    # T = Adj FMV = MIN(Gross Sale Consideration, Total FMV) — only if FMV>0
                    ws_cm.write_formula(row_cm, CM_COLS.index("Adj. FMV (lower of Sale & FMV)"),
                        f"=IF({S}{xr}>0,MIN({O}{xr},{S}{xr}),0)", F_CM_FORMULA)

                    T = _cl("Adj. FMV (lower of Sale & FMV)")
                    # U = Adj Cost (no indexation) = MAX(Gross Cost, Adj FMV)
                    ws_cm.write_formula(row_cm, CM_COLS.index("Adj. Cost (no indexation)"),
                        f"=IF({T}{xr}>0,MAX({Q}{xr},{T}{xr}),{Q}{xr})", F_CM_FORMULA)

                    U = _cl("Adj. Cost (no indexation)")
                    # V = Cost with Indexation = MAX(Indexed Cost, Adj FMV)
                    ws_cm.write_formula(row_cm, CM_COLS.index("Cost with Indexation"),
                        f"=IF({T}{xr}>0,MAX({W}{xr},{T}{xr}),{W}{xr})", F_CM_FORMULA)

                    V = _cl("Cost with Indexation")
                    # STCG = if Short term → Sale - Adj Cost - Transfer Exp
                    ws_cm.write_formula(row_cm, CM_COLS.index("STCG (Rs.)"),
                        f'=IF(ISNUMBER(SEARCH("Short",{L}{xr})),{O}{xr}-{U}{xr}-{X}{xr},"")',
                        F_CM_FORMULA)

                    # LTCG w/o Indexation = if Long term → Sale - Adj Cost - Transfer Exp
                    ws_cm.write_formula(row_cm, CM_COLS.index("LTCG w/o Indexation (Rs.)"),
                        f'=IF(ISNUMBER(SEARCH("Long",{L}{xr})),{O}{xr}-{U}{xr}-{X}{xr},"")',
                        F_CM_FORMULA)

                    Z_col = _cl("LTCG w/o Indexation (Rs.)")
                    # LTCG with Indexation = if Long term AND indexed cost available
                    ws_cm.write_formula(row_cm, CM_COLS.index("LTCG with Indexation (Rs.)"),
                        f'=IF(AND(ISNUMBER(SEARCH("Long",{L}{xr})),{V}{xr}>0),{O}{xr}-{V}{xr}-{X}{xr},"")',
                        F_CM_FORMULA)

                    AA_col = _cl("LTCG with Indexation (Rs.)")
                    # Tax @10% = Y if any LTCG
                    ws_cm.write_formula(row_cm, CM_COLS.index("Tax @10%"),
                        f'=IF(OR(ISNUMBER({Z_col}{xr}),ISNUMBER({AA_col}{xr})),"Y","")',
                        F_DEFAULT)

                    row_cm += 1

            group_end = row_cm - 1
            if group_start > group_end:
                continue

            # Subtotal row — sums input + gain cols
            sub_lbl = f"Subtotal — {sft_code}"
            merge_end_cm = min(cm_num_idx) - 1 if cm_num_idx else ncols_cm - 1
            ws_cm.write_blank(row_cm, 0, None, F_CM_SUB_LBL)
            ws_cm.merge_range(row_cm, 1, row_cm, merge_end_cm, sub_lbl, F_CM_SUB_LBL)
            for ci in cm_subtot_idx:
                cl = _col_letter(ci)
                ws_cm.write_formula(row_cm, ci,
                    f"=SUM({cl}{xl_row(group_start)}:{cl}{xl_row(group_end)})",
                    F_CM_SUB_NUM)
            ws_cm.set_row(row_cm, 14)
            subtotal_rows_cm.append((sft_code, ind_name, row_cm))
            row_cm += 1

        # Grand total — sums subtotal rows only
        grand_lbl_cm = f"GRAND TOTAL — {CM_WS_NAME}"
        merge_end_cm = min(cm_num_idx) - 1 if cm_num_idx else ncols_cm - 1
        ws_cm.write_blank(row_cm, 0, None, F_GRAND_LBL)
        ws_cm.merge_range(row_cm, 1, row_cm, merge_end_cm, grand_lbl_cm, F_GRAND_LBL)
        for ci in cm_subtot_idx:
            cl = _col_letter(ci)
            ws_cm.write_formula(row_cm, ci,
                "=" + "+".join(f"{cl}{xl_row(sr_row)}" for _, _, sr_row in subtotal_rows_cm),
                F_GRAND_NUM)
        ws_cm.set_row(row_cm, 15)
        row_cm += 1

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

        sc_col_cm = CM_COLS.index("Gross Sale Consideration")
        sc_letter_cm = _col_letter(sc_col_cm)

        for sft_code, ind_name, sub_row in subtotal_rows_cm:
            # Sales Consideration from consolidated subtotal row
            consol_ref = f"{sc_letter_cm}{xl_row(sub_row)}"
            # Sales Consideration grand total from individual sheet grand total row
            # Individual sheet grand total is always the last non-blank row
            # We reference via INDIRECT so it works without storing the row number
            ind_sheet_safe = ind_name.replace("'", "''")
            ind_ref = f"'{ind_sheet_safe}'!{sc_letter_cm}{xl_row(sub_row)}"
            # Actually, individual sheets have same col layout only for SFT-17
            # For SFT-18 Sales Consideration is at a different column
            # Get it properly from F_GRAND_NUM row of the individual sheet
            # Simpler: use SUMIF on individual sheet col C (Source col) — but grand total is reliable
            # Get Sales Consideration col in the individual sheet
            ind_defn = _SFT_SHEET_DEF.get(sft_code)
            ind_grand_row = _sheet_grand_row.get(ind_name)
            if ind_defn and ind_grand_row is not None:
                _, ind_sup, _, _ = ind_defn
                try:
                    sc_col_ind = ind_sup.index("Sales Consideration") + 2  # +2 for Sr./Source
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
                except (ValueError, IndexError):
                    pass

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

    # ── Demand & Refund, Proceedings ─────────────────────────────────────
    _write_generic_section("Demand and Refund", sections.get("demandAndRefund"), TC_GENERAL)
    for sec in sections_list:
        title = sec.get("title", "")
        if "pending" in title.lower():
            _write_generic_section("Pending Proceedings", sec, TC_GENERAL)
        elif "complet" in title.lower():
            _write_generic_section("Completed Proceedings", sec, TC_GENERAL)

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
    src_base = os.path.splitext(os.path.basename(json_path))[0]
    parent   = os.path.dirname(src_dir)

    if os.path.basename(src_dir) == "Raw JSON":
        dec_dir  = os.path.join(parent, "Decrypted JSON")
        xlsx_dir = os.path.join(parent, "Excel")
        os.makedirs(dec_dir,  exist_ok=True)
        os.makedirs(xlsx_dir, exist_ok=True)
    else:
        dec_dir  = src_dir
        xlsx_dir = src_dir

    dec_path  = os.path.join(dec_dir,  src_base + "_decrypted.json")
    xlsx_path = os.path.join(xlsx_dir, src_base + ".xlsx")

    with open(dec_path, "w", encoding="utf-8") as _f:
        _json.dump(data, _f, ensure_ascii=False, indent=2)
    _log(f"[AIS] Decrypted JSON saved: {dec_path}")
    _log(f"[AIS] Building Excel workbook for {assessee_name} — FY {fy}…")

    result_path = _write_ais_xlsx(
        data, xlsx_path, pan_in_file, fy, download_date, assessee_name, log_callback)

    _log(f"[AIS] Saved: {result_path}")
    return result_path
