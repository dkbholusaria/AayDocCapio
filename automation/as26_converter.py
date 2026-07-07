"""
26AS TXT → Excel + HTML converter.

Public API:
    convert_26as_txt(txt_path, log_callback=None) -> (xlsx_path, html_path)
"""

import os
import re
from datetime import datetime

# ── Part metadata ──────────────────────────────────────────────────────────────

PART_META = {
    # Form 26AS (IT Act 1961)
    "I":    {"title": "TDS — Salary / Professional / Interest / VDA",              "credit": True},
    "II":   {"title": "TDS on Interest (15G/15H — No TDS Deducted)",               "credit": True},
    "III":  {"title": "TDS on Winnings / Benefits / VDA (Tax Paid Before Release)", "credit": True},
    "IV":   {"title": "TDS u/s 194IA/IB/M/S (Seller of Property / VDA)",           "credit": True},
    "V":    {"title": "26QE — Seller of Virtual Digital Asset",                     "credit": True},
    "VI":   {"title": "TCS — Tax Collected at Source",                              "credit": True},
    "VII":  {"title": "Refunds Paid",                                               "credit": False},
    "VIII": {"title": "TDS u/s 194IA/IB/M/S (Buyer of Property / VDA)",            "credit": False},
    "IX":   {"title": "26QE — Buyer of Virtual Digital Asset",                      "credit": False},
    # Form 168 (IT Act 2025) — Parts I-IX reused; X split into X(a)/X(b); XI is new
    "X_A":  {"title": "TDS/TCS Defaults (Processing of Statements)",                "credit": False},
    "X_B":  {"title": "Other Demands Raised by AO",                                 "credit": False},
    "XI":   {"title": "TDS/TCS Credit by AO u/s 398",                               "credit": True},
}

NON_FINAL_STATUSES = {"U", "M", "O", "P", "Z"}

STATUS_FULL = {
    "F": "Final",
    "U": "Unmatched",
    "M": "Matched",
    "O": "Overbooked",
    "P": "Provisional",
    "Z": "Mismatch",
}

# ── Parser ─────────────────────────────────────────────────────────────────────

def _parse(txt_path: str) -> dict:
    """Return a dict with keys: header, parts.
    header = {field: value, ...}
    parts  = { "I": {"rows": [...], "empty": bool}, ... }
    Each row is a dict of field->value.
    """
    with open(txt_path, encoding="utf-8", errors="replace") as f:
        raw = f.read()

    lines = [ln.rstrip("\n\r") for ln in raw.splitlines()]

    # ── File header ────────────────────────────────────────────────────────
    # Form 26AS: line 0 blank, line 1 title, line 2 keys, line 3 values
    # Form 168:  line 0 title (^Form 168/...^), line 1 keys, line 2 values
    # Detect by checking whether line 0 starts with "^Form 168"
    if lines[0].startswith("^Form 168") or lines[0].startswith("^FORM 168"):
        header_keys   = [c.strip() for c in lines[1].split("^") if c.strip()]
        header_values = [c.strip() for c in lines[2].split("^")] if len(lines) > 2 else []
        parts_start   = 3
    else:
        header_keys   = [c.strip() for c in lines[2].split("^") if c.strip()]
        header_values = [c.strip() for c in lines[3].split("^")] if len(lines) > 3 else []
        parts_start   = 4
    header = dict(zip(header_keys, header_values))

    # ── Split into Part blocks ─────────────────────────────────────────────
    # Form 26AS uses:  ^PART-I –   ^PART-II –   ^PART-III –  etc.
    # Form 168 uses:   ^PART I -   ^PART-II     ^PART III-   ^PART X (a)-  ^PART XI -
    # Regex captures the roman numeral; sub-parts like X(a)/X(b) are captured as "X_A"/"X_B"
    part_re = re.compile(
        r"^\^PART[-\s]*(X\s*\(([ab])\)|([IVX]+))\s*[-–(\s]",
        re.IGNORECASE,
    )
    no_txn_re = re.compile(r"No Transactions Present", re.IGNORECASE)

    parts = {}
    current_part = None
    current_lines = []

    for ln in lines[parts_start:]:
        m = part_re.match(ln)
        if m:
            if current_part:
                parts[current_part] = current_lines
            if m.group(2):
                # Sub-part: X(a) or X(b)
                current_part = f"X_{m.group(2).upper()}"
            else:
                current_part = m.group(3).upper()
            current_lines = []
        elif current_part:
            current_lines.append(ln)

    if current_part:
        parts[current_part] = current_lines

    # ── Parse each Part ────────────────────────────────────────────────────
    parsed_parts = {}
    for roman, plines in parts.items():
        # Skip legacy X (undivided) — Form 168 uses X_A / X_B
        if roman == "X":
            continue
        # Check empty
        empty = any(no_txn_re.search(ln) for ln in plines)
        if empty:
            parsed_parts[roman] = {"empty": True, "rows": [], "col_headers": []}
            continue

        # Find column header lines (first non-blank line = summary headers,
        # second non-blank = detail headers)
        non_blank = [ln for ln in plines if ln.strip()]
        if not non_blank:
            parsed_parts[roman] = {"empty": True, "rows": [], "col_headers": []}
            continue

        summary_headers = [c.strip() for c in non_blank[0].split("^")]
        detail_headers  = []
        # detail header = first line that starts with ^ (blank first field)
        for ln in non_blank[1:]:
            if ln.startswith("^"):
                detail_headers = [c.strip() for c in ln.split("^")]
                break

        rows = []
        i = 0
        data_lines = non_blank[1:]  # skip the summary-col header line

        # skip detail header line itself
        skip_next_detail_hdr = True

        while i < len(data_lines):
            ln = data_lines[i]
            if not ln.strip():
                i += 1
                continue

            fields = [c.strip() for c in ln.split("^")]

            # Deductor/summary row: first field is a digit (Sr. No.)
            if fields[0].isdigit():
                # Skip detail-header lines that appear after each deductor block
                # (they start with ^ and contain "Sr. No." etc.)
                deductor_row = dict(zip(summary_headers, fields))
                deductor_row["_type"] = "deductor"
                deductor_row["_details"] = []
                i += 1
                # Collect detail rows (start with ^)
                while i < len(data_lines):
                    dl = data_lines[i]
                    if not dl.strip():
                        i += 1
                        break
                    dfields = [c.strip() for c in dl.split("^")]
                    # skip if it looks like a header (contains "Sr. No." or "Section")
                    if dfields[0] == "" and dfields[1:2] == ["Sr. No."]:
                        i += 1
                        continue
                    if dfields[0] == "" and dfields[1].isdigit():
                        detail_row = dict(zip(detail_headers, dfields))
                        detail_row["_type"] = "detail"
                        deductor_row["_details"].append(detail_row)
                        i += 1
                    else:
                        break
                rows.append(deductor_row)
            else:
                i += 1

        parsed_parts[roman] = {
            "empty": False,
            "rows": rows,
            "col_headers": summary_headers,
            "detail_headers": detail_headers,
        }

    return {"header": header, "parts": parsed_parts}


def _fmt_num(val: str) -> float | None:
    """Convert string number to float; None if blank/dash."""
    v = val.strip().replace(",", "")
    if not v or v == "-":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _ind(n: float | None) -> str:
    """Format float as Indian number string for HTML."""
    if n is None:
        return ""
    if n < 0:
        return f"({abs(n):,.2f})"
    return f"{n:,.2f}"


# ── HTML generator ────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing:border-box; margin:0; padding:0; }
html, body { height:100%; }
body { font-family:"Segoe UI",Calibri,system-ui,-apple-system,Arial,sans-serif; font-size:12px; background:#e8e8e8;
  display:flex; flex-direction:column; }
.tab-bar { display:flex; align-items:flex-end; flex-wrap:wrap; background:#d6d6d6;
  border-bottom:2px solid #1a5c32; padding:4px 8px 0; gap:2px; flex-shrink:0; }
.tab { padding:5px 12px; background:#c0c0c0; border:1px solid #a0a0a0;
  border-bottom:none; border-radius:3px 3px 0 0; cursor:pointer; font-size:11px;
  color:#333; white-space:nowrap; transition:background 0.12s; }
.tab:hover { background:#d8d8d8; }
.tab.active { background:#fff; color:#1a5c32; font-weight:700; border-color:#1a5c32; }
.sheet { display:none; background:#fff; flex-direction:column; flex:1; min-height:0; }
.sheet.active { display:flex; }
.brand { background:linear-gradient(135deg,#0A1628 0%,#1e3a5f 100%);
  color:#fff; padding:10px 20px; display:flex; align-items:center; gap:14px; flex-shrink:0; }
.brand-title { font-size:16px; font-weight:700; }
.brand-sub { font-size:11px; color:#94A3B8; margin-top:2px; }
.brand-badge { margin-left:auto; background:#217346; color:#fff; padding:3px 10px;
  border-radius:10px; font-size:10px; font-weight:600; }
.freeze-bar { background:#fffbe6; border-bottom:2px solid #e6b800; padding:3px 10px;
  font-size:10px; color:#7a5c00; flex-shrink:0; }
.note-bar { background:#e8f0fe; border-bottom:1px solid #bad0f8; padding:4px 10px;
  font-size:10px; color:#1a3a8f; flex-shrink:0; }
.tbl-wrap { overflow-x:auto; overflow-y:auto; flex:1; min-height:0; }
.footer { background:#0A1628; color:#94A3B8; font-size:10px; padding:4px 14px;
  display:flex; align-items:center; gap:16px; flex-shrink:0; }
.footer a { color:#7da9d8; text-decoration:none; }
.footer a:hover { color:#fff; text-decoration:underline; }
.footer-copy { margin-right:auto; }
table { border-collapse:collapse; width:100%; }
td,th { border:1px solid #d0d0d0; padding:3px 7px; white-space:nowrap; font-size:11px; }
thead th { background:#1a5c32; color:#fff; font-weight:700; text-align:center;
  position:sticky; top:0; z-index:2; }
tr.alt td { background:#f5fbf5; }
tr:hover td { background:#e8f5e9; }
tr.subtotal td { background:#d0e8c8; font-weight:700; border-top:2px solid #1a5c32; color:#1a3a22; }
tr.subtotal:hover td { background:#c4e0bc; }
tr.grandtotal td { background:#0A1628; color:#fff; font-weight:700; border-top:2px solid #fff; }
tr.grandtotal td.num { color:#7fff8a; }
tr.empty-note td { background:#fff8f0; color:#a05000; font-style:italic; text-align:center; padding:10px; }
td.ded-name { font-weight:700; color:#1a3a22; }
td.num { text-align:right; font-family:"Cascadia Code","Cascadia Mono",Consolas,"Courier New",monospace; }
td.label { background:#f0f4f0; font-weight:600; color:#444; min-width:160px; }
td.link a { color:#1155cc; text-decoration:underline; cursor:pointer; font-weight:600; }
td.link a:hover { color:#0b3d91; }
td.sec { color:#555; font-style:italic; }
.st { display:inline-block; padding:1px 6px; border-radius:3px; font-size:10px; font-weight:700; }
.st-F { background:#d4edda; color:#155724; }
.st-M { background:#d1ecf1; color:#0c5460; }
.st-U { background:#fff3cd; color:#856404; }
.st-O { background:#ffe0b2; color:#7a3000; }
.st-P { background:#e2d9f3; color:#4a235a; }
.st-Z { background:#f8d7da; color:#721c24; }
tr.non-final td { background:#fff0f0 !important; color:#800 !important; }
tr.non-final td .st { border:1px solid #f5c2c7; }
tr.non-final:hover td { background:#ffe0e0 !important; }
.rmk { display:inline-block; padding:1px 5px; border-radius:3px; font-size:10px;
  background:#f0f0f0; color:#333; border:1px solid #ccc; }
.rmk-G { background:#fff3cd; color:#856404; border-color:#ffc107; }
.rmk-B { background:#d1ecf1; color:#0c5460; border-color:#bee5eb; }
.sec-hdr td { background:#1a5c32 !important; color:#fff !important;
  border-color:#1a5c32; font-weight:700; padding:5px 10px; font-size:11px; }
.ass-tbl td { padding:5px 10px; }
.leg-title { font-size:13px; font-weight:700; padding:8px 10px;
  background:#1a5c32; color:#fff; }
td.pbadge { background:#0A1628 !important; color:#fff !important; font-weight:700; text-align:center;
  font-size:10px; }
"""

_JS = """
function show(id) {
  document.querySelectorAll('.sheet').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('sheet-' + id).classList.add('active');
  const idx = TAB_IDS.indexOf(id);
  if (idx >= 0) document.querySelectorAll('.tab')[idx].classList.add('active');
}
function jumpTo(rowId) {
  setTimeout(() => {
    const el = document.getElementById(rowId);
    if (!el) return;
    const orig = el.style.outline;
    el.scrollIntoView({behavior:'smooth', block:'center'});
    el.style.outline = '3px solid #e6b800';
    setTimeout(() => { el.style.outline = orig; }, 2200);
  }, 60);
}
"""

def _st_badge(status: str) -> str:
    s = (status or "").strip()
    css = f"st-{s}" if s else ""
    return f'<span class="st {css}">{s}</span>' if s else ""


def _rmk_badge(rmk: str) -> str:
    r = (rmk or "").strip()
    if not r or r == "-":
        return ""
    css = f"rmk-{r}" if r in ("G", "B") else "rmk"
    return f'<span class="{css}">{r}</span>'


def _non_final_class(rows_for_deductor) -> bool:
    """True if any detail row has non-F status."""
    for r in rows_for_deductor:
        st = (r.get("Status of Booking") or r.get("Status") or "").strip()
        if st and st not in ("F", "", "-"):
            return True
    return False


def _td_num(val) -> str:
    if isinstance(val, (int, float)):
        v = val
    else:
        v = _fmt_num(str(val))
    if v is None:
        return '<td class="num"></td>'
    return f'<td class="num">{_ind(v)}</td>'


# ── Per-Part HTML builders ────────────────────────────────────────────────────

def _html_part_I_VI(roman: str, pdata: dict, row_ids: dict) -> str:
    """Parts I and VI: deductor + detail rows, flat layout."""
    is_VI = roman == "VI"
    if is_VI:
        hdrs = ["Collector Name", "TAN", "Section", "Transaction Date",
                "Booking Status", "Remarks",
                "Total Amount Paid/Debited (₹)", "Tax Collected (₹)", "TCS Deposited (₹)"]
    else:
        hdrs = ["Deductor Name", "TAN", "Section", "Transaction Date",
                "Booking Status", "Remarks",
                "Amount Paid/Credited (₹)", "Tax Deducted (₹)", "TDS Deposited (₹)"]

    th = "".join(f"<th>{h}</th>" for h in hdrs)
    rows_html = []
    sr = 0
    alt = False

    for ded in pdata["rows"]:
        sr += 1
        name = ded.get("Name of Deductor") or ded.get("Name of Collector") or ""
        tan  = ded.get("TAN of Deductor")  or ded.get("TAN of Collector")  or ""
        details = ded.get("_details", [])

        has_nf = _non_final_class(details)
        first_row_id = f"p{roman}r{sr}"
        row_ids[roman][sr] = {"name": name, "tan": tan}

        for di, d in enumerate(details):
            sec    = d.get("Section", "")
            txdate = d.get("Transaction Date", "")
            status = d.get("Status of Booking", "")
            rmk    = d.get("Remarks", "")
            amt    = _fmt_num(d.get("Amount Paid / Credited(Rs.)") or d.get("Amount Paid / Debited(Rs.)") or d.get("Total Amount Paid / Debited(Rs.)") or "")
            tds    = _fmt_num(d.get("Tax Deducted(Rs.)") or d.get("Tax Collected(Rs.)") or "")
            dep    = _fmt_num(d.get("TDS Deposited(Rs.)") or d.get("TCS Deposited(Rs.)") or "")

            nf_cls  = " non-final" if status.strip() in NON_FINAL_STATUSES else ""
            alt_cls = " alt" if alt else ""
            row_id  = f' id="{first_row_id}"' if di == 0 else ""

            rows_html.append(
                f'<tr class="{alt_cls}{nf_cls}"{row_id}>'
                f'<td class="ded-name">{name}</td>'
                f'<td>{tan}</td>'
                f'<td class="sec">{sec}</td>'
                f'<td>{txdate}</td>'
                f'<td>{_st_badge(status)}</td>'
                f'<td>{_rmk_badge(rmk)}</td>'
                f'{_td_num(amt)}{_td_num(tds)}{_td_num(dep)}'
                f'</tr>'
            )
            alt = not alt

        # Subtotal
        s_amt = _fmt_num(ded.get("Total Amount Paid / Credited(Rs.)") or ded.get("Total Amount Paid / Debited(Rs.)") or "")
        s_tds = _fmt_num(ded.get("Total Tax Deducted(Rs.)")  or ded.get("Total Tax Collected(Rs.)")  or "")
        s_dep = _fmt_num(ded.get("Total TDS Deposited(Rs.)") or ded.get("Total TCS Deposited(Rs.)") or "")
        nf_warn = " ⚠" if has_nf else ""
        rows_html.append(
            f'<tr class="subtotal">'
            f'<td colspan="5" style="text-align:right;padding-right:8px">'
            f'Sr. {sr}&nbsp;·&nbsp;Subtotal — {name}{nf_warn}</td>'
            f'<td></td>'
            f'{_td_num(s_amt)}{_td_num(s_tds)}{_td_num(s_dep)}'
            f'</tr>'
        )

    # Grand total
    g_amt = sum(_fmt_num(d.get("Total Amount Paid / Credited(Rs.)") or d.get("Total Amount Paid / Debited(Rs.)") or "") or 0 for d in pdata["rows"])
    g_tds = sum(_fmt_num(d.get("Total Tax Deducted(Rs.)") or d.get("Total Tax Collected(Rs.)") or "") or 0 for d in pdata["rows"])
    g_dep = sum(_fmt_num(d.get("Total TDS Deposited(Rs.)") or d.get("Total TCS Deposited(Rs.)") or "") or 0 for d in pdata["rows"])
    rows_html.append(
        f'<tr class="grandtotal">'
        f'<td colspan="5" style="text-align:right;padding-right:8px">GRAND TOTAL — Part-{roman}</td>'
        f'<td></td>'
        f'{_td_num(g_amt)}{_td_num(g_tds)}{_td_num(g_dep)}'
        f'</tr>'
    )

    return (
        f'<div class="tbl-wrap"><table>'
        f'<thead><tr>{th}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>'
    )


def _html_part_II(pdata: dict, row_ids: dict) -> str:
    hdrs = ["Deductor Name", "TAN", "Section", "Transaction Date",
            "Date of Booking", "Remarks",
            "Amount Paid/Credited (₹)", "Tax Deducted (₹)", "TDS Deposited (₹)"]
    th = "".join(f"<th>{h}</th>" for h in hdrs)
    rows_html = []
    sr = 0
    alt = False

    for ded in pdata["rows"]:
        sr += 1
        name = ded.get("Name of Deductor", "")
        tan  = ded.get("TAN of Deductor", "")
        details = ded.get("_details", [])
        first_row_id = f"pIIr{sr}"
        row_ids["II"][sr] = {"name": name, "tan": tan}

        for di, d in enumerate(details):
            sec    = d.get("Section", "")
            txdate = d.get("Transaction Date", "")
            bkdate = d.get("Date of Booking", "")
            rmk    = d.get("Remarks", "")
            amt    = _fmt_num(d.get("Amount Paid / Credited(Rs.)", ""))
            tds    = _fmt_num(d.get("Tax Deducted(Rs.)", ""))
            dep    = _fmt_num(d.get("TDS Deposited(Rs.)", ""))
            status = d.get("Status of Booking", "")
            nf_cls  = " non-final" if status.strip() in NON_FINAL_STATUSES else ""
            alt_cls = " alt" if alt else ""
            row_id  = f' id="{first_row_id}"' if di == 0 else ""
            rows_html.append(
                f'<tr class="{alt_cls}{nf_cls}"{row_id}>'
                f'<td class="ded-name">{name}</td><td>{tan}</td>'
                f'<td class="sec">{sec}</td><td>{txdate}</td><td>{bkdate}</td>'
                f'<td>{_rmk_badge(rmk)}</td>'
                f'{_td_num(amt)}{_td_num(tds)}{_td_num(dep)}</tr>'
            )
            alt = not alt

        s_amt = _fmt_num(ded.get("Total Amount Paid / Credited(Rs.)", ""))
        s_tds = _fmt_num(ded.get("Total Tax Deducted(Rs.)", ""))
        s_dep = _fmt_num(ded.get("Total TDS Deposited(Rs.)", ""))
        rows_html.append(
            f'<tr class="subtotal">'
            f'<td colspan="5" style="text-align:right;padding-right:8px">Sr. {sr}&nbsp;·&nbsp;Subtotal — {name}</td>'
            f'<td></td>{_td_num(s_amt)}{_td_num(s_tds)}{_td_num(s_dep)}</tr>'
        )

    g_amt = sum((_fmt_num(d.get("Total Amount Paid / Credited(Rs.)", "")) or 0) for d in pdata["rows"])
    g_tds = sum((_fmt_num(d.get("Total Tax Deducted(Rs.)", "")) or 0)           for d in pdata["rows"])
    g_dep = sum((_fmt_num(d.get("Total TDS Deposited(Rs.)", "")) or 0)          for d in pdata["rows"])
    rows_html.append(
        f'<tr class="grandtotal"><td colspan="5" style="text-align:right;padding-right:8px">GRAND TOTAL — Part-II</td>'
        f'<td></td>{_td_num(g_amt)}{_td_num(g_tds)}{_td_num(g_dep)}</tr>'
    )
    return (
        f'<div class="note-bar">ℹ Part-II — Interest/dividend where 15G/15H submitted (no TDS deducted)</div>'
        f'<div class="tbl-wrap"><table>'
        f'<thead><tr>{th}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>'
    )


def _html_part_III(pdata: dict, row_ids: dict) -> str:
    hdrs = ["Deductor Name", "TAN", "Section", "Transaction Date",
            "Booking Status", "Remarks", "Amount Paid/Credited (₹)"]
    th = "".join(f"<th>{h}</th>" for h in hdrs)
    rows_html = []
    sr = 0
    alt = False

    for ded in pdata["rows"]:
        sr += 1
        name = ded.get("Name of Deductor", "")
        tan  = ded.get("TAN of Deductor", "")
        details = ded.get("_details", [])
        first_row_id = f"pIIIr{sr}"
        row_ids["III"][sr] = {"name": name, "tan": tan}

        for di, d in enumerate(details):
            sec    = d.get("Section", "")
            txdate = d.get("Transaction Date", "")
            status = d.get("Status of Booking", "")
            rmk    = d.get("Remarks", "")
            amt    = _fmt_num(d.get("Amount Paid / Credited(Rs.)", ""))
            nf_cls  = " non-final" if status.strip() in NON_FINAL_STATUSES else ""
            alt_cls = " alt" if alt else ""
            row_id  = f' id="{first_row_id}"' if di == 0 else ""
            rows_html.append(
                f'<tr class="{alt_cls}{nf_cls}"{row_id}>'
                f'<td class="ded-name">{name}</td><td>{tan}</td>'
                f'<td class="sec">{sec}</td><td>{txdate}</td>'
                f'<td>{_st_badge(status)}</td><td>{_rmk_badge(rmk)}</td>'
                f'{_td_num(amt)}</tr>'
            )
            alt = not alt

        s_amt = _fmt_num(ded.get("Total Amount Paid / Credited(Rs.)", ""))
        rows_html.append(
            f'<tr class="subtotal">'
            f'<td colspan="5" style="text-align:right;padding-right:8px">Sr. {sr}&nbsp;·&nbsp;Subtotal — {name}</td>'
            f'<td></td>{_td_num(s_amt)}</tr>'
        )

    g_amt = sum((_fmt_num(d.get("Total Amount Paid / Credited(Rs.)", "")) or 0) for d in pdata["rows"])
    rows_html.append(
        f'<tr class="grandtotal"><td colspan="5" style="text-align:right;padding-right:8px">GRAND TOTAL — Part-III</td>'
        f'<td></td>{_td_num(g_amt)}</tr>'
    )
    return (
        f'<div class="note-bar">ℹ Part-III — Tax paid before release (winnings/benefits/VDA). No separate TDS column.</div>'
        f'<div class="tbl-wrap"><table>'
        f'<thead><tr>{th}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>'
    )


def _html_part_IV_VIII(roman: str, pdata: dict, row_ids: dict) -> str:
    """Parts IV and VIII: property/VDA TDS — flat row per transaction."""
    is_VIII = roman == "VIII"
    if is_VIII:
        hdrs = ["Name of Deductee (Seller/Landlord)", "PAN of Deductee",
                "Ack. No.", "TDS Cert. No.", "Section", "Transaction Date",
                "Date of Deposit", "Booking Status", "Demand Payment",
                "Total Transaction Amount (₹)", "TDS Deposited (₹)", "Other Amount (₹)"]
        name_key = "Name of Deductee"
        pan_key  = "PAN of Deductee"
        note = "ℹ Part-VIII — TDS deducted <strong>by you</strong> as buyer/tenant · Informational only — not included in Summary"
    else:
        hdrs = ["Name of Deductor (Buyer/Tenant)", "PAN of Deductor",
                "Ack. No.", "TDS Cert. No.", "Section", "Transaction Date",
                "Date of Deposit", "Booking Status", "Demand Payment",
                "Total Transaction Amount (₹)", "TDS Deposited (₹)"]
        name_key = "Name of Deductor"
        pan_key  = "PAN of Deductor"
        note = None

    th = "".join(f"<th>{h}</th>" for h in hdrs)
    rows_html = []
    sr = 0
    alt = False

    for ded in pdata["rows"]:
        sr += 1
        name = ded.get(name_key) or ded.get("Name of Deductor") or ""
        pan  = ded.get(pan_key)  or ded.get("PAN of Deductor")  or ""
        ack  = ded.get("Acknowledgement Number", "")
        details = ded.get("_details", [])
        first_row_id = f"p{roman}r{sr}"
        row_ids[roman][sr] = {"name": name, "tan": pan}

        for di, d in enumerate(details):
            cert   = d.get("TDS Certificate Number", "")
            sec    = d.get("Section", "")
            dep_dt = d.get("Date of Deposit", "")
            status = d.get("Status of Booking", "")
            demand = d.get("Demand Payment", "")
            tds    = _fmt_num(d.get("TDS Deposited(Rs.)", ""))
            other  = _fmt_num(d.get("Total Amount Deposited other than TDS(Rs.)", "")) if is_VIII else None
            txdate = ded.get("Transaction Date", "")
            txamt  = _fmt_num(ded.get("Total Transaction Amount(Rs.)", ""))

            nf_cls  = " non-final" if status.strip() in NON_FINAL_STATUSES else ""
            alt_cls = " alt" if alt else ""
            row_id  = f' id="{first_row_id}"' if di == 0 else ""

            other_td = _td_num(other) if is_VIII else ""
            rows_html.append(
                f'<tr class="{alt_cls}{nf_cls}"{row_id}>'
                f'<td class="ded-name">{name}</td><td>{pan}</td>'
                f'<td>{ack}</td><td>{cert}</td>'
                f'<td class="sec">{sec}</td><td>{txdate}</td><td>{dep_dt}</td>'
                f'<td>{_st_badge(status)}</td><td>{demand}</td>'
                f'{_td_num(txamt)}{_td_num(tds)}{other_td}</tr>'
            )
            alt = not alt

        s_txamt = _fmt_num(ded.get("Total Transaction Amount(Rs.)", ""))
        s_tds   = _fmt_num(ded.get("Total TDS Deposited(Rs.)", ""))
        other_td2 = _td_num(0) if is_VIII else ""
        rows_html.append(
            f'<tr class="subtotal">'
            f'<td colspan="8" style="text-align:right;padding-right:8px">Sr. {sr}&nbsp;·&nbsp;Subtotal — {name}</td>'
            f'<td></td>{_td_num(s_txamt)}{_td_num(s_tds)}{other_td2}</tr>'
        )

    g_tx  = sum((_fmt_num(d.get("Total Transaction Amount(Rs.)", "")) or 0) for d in pdata["rows"])
    g_tds = sum((_fmt_num(d.get("Total TDS Deposited(Rs.)", "")) or 0)      for d in pdata["rows"])
    other_td3 = _td_num(0) if is_VIII else ""
    rows_html.append(
        f'<tr class="grandtotal">'
        f'<td colspan="8" style="text-align:right;padding-right:8px">GRAND TOTAL — Part-{roman}</td>'
        f'<td></td>{_td_num(g_tx)}{_td_num(g_tds)}{other_td3}</tr>'
    )
    prefix = f'<div class="note-bar">{note}</div>' if note else ""
    return (
        prefix +
        f'<div class="tbl-wrap"><table>'
        f'<thead><tr>{th}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>'
    )


def _html_part_V(pdata: dict, row_ids: dict) -> str:
    hdrs = ["Name of Buyer", "PAN of Buyer", "Ack. No.", "Transaction Date",
            "Total Transaction Amount (₹)", "BSR Code", "Date of Deposit",
            "Challan Serial No.", "Total Tax Amount (₹)", "Booking Status",
            "Demand Payment"]
    th = "".join(f"<th>{h}</th>" for h in hdrs)
    rows_html = []
    sr = 0
    alt = False

    for ded in pdata["rows"]:
        sr += 1
        name = ded.get("Name of Buyer", "")
        pan  = ded.get("PAN of Buyer", "")
        ack  = ded.get("Acknowledgement Number", "")
        txdate = ded.get("Transaction Date", "")
        txamt  = _fmt_num(ded.get("Total Transaction Amount(Rs.)", ""))
        details = ded.get("_details", [])
        first_row_id = f"pVr{sr}"
        row_ids["V"][sr] = {"name": name, "tan": pan}

        for di, d in enumerate(details):
            bsr    = d.get("BSR Code", "")
            dep_dt = d.get("Date of Deposit", "")
            challan= d.get("Challan Serial Number", "") or d.get("Challan Serial No.", "")
            tax    = _fmt_num(d.get("Total Tax Amount(Rs.)", ""))
            status = d.get("Status of Booking", "")
            demand = d.get("Demand Payment", "")

            nf_cls  = " non-final" if status.strip() in NON_FINAL_STATUSES else ""
            alt_cls = " alt" if alt else ""
            row_id  = f' id="{first_row_id}"' if di == 0 else ""
            rows_html.append(
                f'<tr class="{alt_cls}{nf_cls}"{row_id}>'
                f'<td class="ded-name">{name}</td><td>{pan}</td><td>{ack}</td>'
                f'<td>{txdate}</td>{_td_num(txamt)}'
                f'<td>{bsr}</td><td>{dep_dt}</td><td>{challan}</td>'
                f'{_td_num(tax)}<td>{_st_badge(status)}</td><td>{demand}</td></tr>'
            )
            alt = not alt

        s_txamt = _fmt_num(ded.get("Total Transaction Amount(Rs.)", ""))
        rows_html.append(
            f'<tr class="subtotal">'
            f'<td colspan="3" style="text-align:right;padding-right:8px">Sr. {sr}&nbsp;·&nbsp;Subtotal — {name}</td>'
            f'{_td_num(s_txamt)}<td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>'
        )

    g_tx = sum((_fmt_num(d.get("Total Transaction Amount(Rs.)", "")) or 0) for d in pdata["rows"])
    rows_html.append(
        f'<tr class="grandtotal">'
        f'<td colspan="3" style="text-align:right;padding-right:8px">GRAND TOTAL — Part-V</td>'
        f'{_td_num(g_tx)}<td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>'
    )
    return (
        f'<div class="tbl-wrap"><table>'
        f'<thead><tr>{th}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>'
    )


def _html_part_VII(pdata: dict) -> str:
    hdrs = ["Assessment Year", "Mode", "Refund Issued", "Nature of Refund",
            "Amount of Refund (₹)", "Interest (₹)", "Date of Payment", "Remarks"]
    th = "".join(f"<th>{h}</th>" for h in hdrs)
    rows_html = []
    alt = False

    for ded in pdata["rows"]:
        # Part VII has no deductor/detail split — each row is a refund record
        # The summary row itself carries the fields
        ay     = ded.get("Assessment Year", "")
        mode   = ded.get("Mode", "")
        issued = ded.get("Refund Issued", "")
        nature = ded.get("Nature of Refund", "")
        amt    = _fmt_num(ded.get("Amount of Refund(Rs.)", ""))
        intr   = _fmt_num(ded.get("Interest(Rs.)", ""))
        dt     = ded.get("Date of Payment", "")
        rmk    = ded.get("Remarks", "")
        alt_cls = " alt" if alt else ""
        rows_html.append(
            f'<tr class="{alt_cls}"><td>{ay}</td><td>{mode}</td><td>{issued}</td>'
            f'<td>{nature}</td>{_td_num(amt)}{_td_num(intr)}<td>{dt}</td>'
            f'<td>{_rmk_badge(rmk)}</td></tr>'
        )
        alt = not alt

    if not rows_html:
        rows_html = ['<tr class="empty-note"><td colspan="8">No Transactions Present</td></tr>']

    return (
        f'<div class="note-bar">ℹ Part-VII — Refunds paid to assessee · Informational only — not included in Summary</div>'
        f'<div class="tbl-wrap"><table>'
        f'<thead><tr>{th}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>'
    )


def _html_part_IX(pdata: dict, row_ids: dict) -> str:
    hdrs = ["Name of Seller", "PAN of Seller", "Ack. No.", "Transaction Date",
            "Total Transaction Amount (₹)", "BSR Code", "Date of Deposit",
            "Challan Serial No.", "Total Tax Amount (₹)", "Booking Status",
            "Demand Payment", "Other Amount Deposited (₹)"]
    th = "".join(f"<th>{h}</th>" for h in hdrs)
    rows_html = []
    sr = 0
    alt = False

    for ded in pdata["rows"]:
        sr += 1
        name = ded.get("Name of Seller", "")
        pan  = ded.get("PAN of Seller", "")
        ack  = ded.get("Acknowledgement Number", "")
        txdate = ded.get("Transaction Date", "")
        txamt  = _fmt_num(ded.get("Total Transaction Amount(Rs.)", ""))
        details = ded.get("_details", [])
        first_row_id = f"pIXr{sr}"
        row_ids["IX"][sr] = {"name": name, "tan": pan}

        for di, d in enumerate(details):
            bsr    = d.get("BSR Code", "")
            dep_dt = d.get("Date of Deposit", "")
            challan= d.get("Challan Serial Number", "") or d.get("Challan Serial No.", "")
            tax    = _fmt_num(d.get("Total Tax Amount(Rs.)", ""))
            status = d.get("Status of Booking", "")
            demand = d.get("Demand Payment", "")
            other  = _fmt_num(d.get("Total Amount Deposited other than TDS(Rs.)", ""))

            nf_cls  = " non-final" if status.strip() in NON_FINAL_STATUSES else ""
            alt_cls = " alt" if alt else ""
            row_id  = f' id="{first_row_id}"' if di == 0 else ""
            rows_html.append(
                f'<tr class="{alt_cls}{nf_cls}"{row_id}>'
                f'<td class="ded-name">{name}</td><td>{pan}</td><td>{ack}</td>'
                f'<td>{txdate}</td>{_td_num(txamt)}'
                f'<td>{bsr}</td><td>{dep_dt}</td><td>{challan}</td>'
                f'{_td_num(tax)}<td>{_st_badge(status)}</td><td>{demand}</td>{_td_num(other)}</tr>'
            )
            alt = not alt

    if not rows_html:
        rows_html = ['<tr class="empty-note"><td colspan="12">No Transactions Present</td></tr>']

    return (
        f'<div class="note-bar">ℹ Part-IX — 26QE transactions as Buyer of VDA · Informational only — not included in Summary</div>'
        f'<div class="tbl-wrap"><table>'
        f'<thead><tr>{th}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>'
    )


def _match_ded(rows, name, tan):
    """Match deductor row by name+TAN/PAN composite key; fall back to name-only when TAN is blank."""
    name_fields = ("Name of Deductor", "Name of Collector", "Name of Buyer", "Name of Deductee")
    tan_fields  = ("TAN of Deductor", "TAN of Collector", "PAN of Deductee",
                   "PAN of Buyer", "PAN of Seller", "PAN of Deductor")
    def _n(d): return (next((d.get(f) for f in name_fields if d.get(f)), "") or "").strip()
    def _t(d): return (next((d.get(f) for f in tan_fields  if d.get(f)), "") or "").strip()
    tan = (tan or "").strip()
    name = (name or "").strip()
    if tan:
        hit = [d for d in rows if _n(d) == name and _t(d) == tan]
        if hit:
            return hit
    return [d for d in rows if _n(d) == name]


def _html_summary(parsed: dict, row_ids: dict) -> str:
    header = parsed["header"]
    parts  = parsed["parts"]

    hdrs = ["Part", "Part Title", "Deductor / Payer / Collector Name", "TAN / PAN",
            "Total Amount (₹)", "Tax Deducted/Collected (₹)", "Tax Deposited (₹)", "⚠ Non-Final Rows"]
    th = "".join(f"<th>{h}</th>" for h in hdrs)
    rows_html = []
    alt = False

    grand_amt = grand_tds = grand_dep = 0.0

    credit_parts = [r for r in ["I","II","III","IV","V","VI"] if r in parts and not parts[r]["empty"]]

    for roman in credit_parts:
        pdata = parts[roman]
        meta  = PART_META.get(roman, {})
        part_label = f"Part-{roman}"
        part_title = meta.get("title", "")
        part_id = f"p{roman}"

        for sr, info in row_ids.get(roman, {}).items():
            name = info["name"]
            tan  = info["tan"]
            row_id = f"p{roman}r{sr}"

            # Find deductor row to get amounts
            ded_rows = _match_ded(pdata["rows"], name, tan)
            amt = tds = dep = 0.0
            has_nf = False
            nf_count = 0
            if ded_rows:
                dr = ded_rows[0]
                amt = _fmt_num(dr.get("Total Amount Paid / Credited(Rs.)") or
                               dr.get("Total Amount Paid / Debited(Rs.)") or
                               dr.get("Total Transaction Amount(Rs.)") or "") or 0
                tds = _fmt_num(dr.get("Total Tax Deducted(Rs.)") or
                               dr.get("Total Tax Collected(Rs.)") or
                               dr.get("Total TDS Deposited(Rs.)") or "") or 0
                dep = _fmt_num(dr.get("Total TDS Deposited(Rs.)") or
                               dr.get("Total TCS Deposited(Rs.)") or "") or 0
                for d in dr.get("_details", []):
                    st = (d.get("Status of Booking") or "").strip()
                    if st in NON_FINAL_STATUSES:
                        has_nf = True
                        nf_count += 1

            grand_amt += amt
            grand_tds += tds
            grand_dep += dep

            nf_cls = " non-final" if has_nf else ""
            alt_cls = " alt" if alt else ""
            nf_cell = (f'<td class="num" style="color:#c00;font-weight:700">{nf_count}</td>'
                       if nf_count else '<td class="num">0</td>')
            nf_name = f" ⚠" if has_nf else ""

            # Part-III has only amount column, no TDS
            if roman == "III":
                tds_cell = '<td class="num">—</td><td class="num">—</td>'
            else:
                tds_cell = f'{_td_num(tds)}{_td_num(dep)}'

            onclick = f"show('{part_id}');jumpTo('{row_id}')"
            rows_html.append(
                f'<tr class="{alt_cls}{nf_cls}">'
                f'<td class="pbadge">{part_label}</td>'
                f'<td>{part_title}</td>'
                f'<td class="link"><a onclick="{onclick}">{name}{nf_name}</a></td>'
                f'<td class="link"><a onclick="{onclick}">{tan}</a></td>'
                f'{_td_num(amt)}{tds_cell}{nf_cell}</tr>'
            )
            alt = not alt

        # Part subtotal
        rows_html.append(
            f'<tr class="subtotal">'
            f'<td colspan="3" style="text-align:right;padding-right:8px">'
            f'{part_label} Subtotal ({len(row_ids.get(roman, {}))} entries)</td>'
            f'<td></td><td></td><td></td><td></td><td></td></tr>'
        )

    rows_html.append(
        f'<tr class="grandtotal">'
        f'<td colspan="3" style="text-align:right;padding-right:8px">GRAND TOTAL (Parts I–VI, credit only)</td>'
        f'<td></td>{_td_num(grand_amt)}{_td_num(grand_tds)}{_td_num(grand_dep)}<td></td></tr>'
    )

    info_parts = [r for r in ["VII","VIII","IX"] if r in parts and not parts[r]["empty"]]
    if info_parts:
        rows_html.append(
            f'<tr><td colspan="8" style="text-align:center;padding:5px;font-style:italic;'
            f'color:#888;font-size:10px">Parts '
            + " · ".join(f"VII" if p == "VII" else p for p in info_parts)
            + f' present but informational only (no tax credit)</td></tr>'
        )

    return (
        f'<div class="freeze-bar">↕ Row 1 frozen · Click name to jump to that deductor\'s row · '
        f'Red = non-Final rows present · Parts VII, VIII &amp; IX excluded (informational)</div>'
        f'<div class="tbl-wrap"><table>'
        f'<thead><tr>{th}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>'
    )


_LEGENDS_HTML = """
<div class="tbl-wrap">
<table>
<tr><td colspan="3" class="leg-title" style="font-size:13px;font-weight:700;padding:8px 10px;background:#1a5c32;color:#fff">Status of Booking — Legend</td></tr>
<tr><td colspan="3" style="padding:4px 10px;font-size:10px;color:#555;background:#f9f9f9">Only <strong>F (Final)</strong> entries are eligible for tax credit. All other statuses are highlighted red in Part sheets.</td></tr>
<tr><th style="width:60px">Code</th><th style="width:120px">Description</th><th>Definition</th></tr>
<tr class="alt"><td style="text-align:center"><span class="st st-U">U</span></td><td>Unmatched</td><td>Deductor has not deposited taxes or furnished incorrect particulars.</td></tr>
<tr><td style="text-align:center"><span class="st st-M">M</span></td><td>Matched</td><td>Challan details in TDS statement match OLTAS records.</td></tr>
<tr class="alt"><td style="text-align:center"><span class="st st-P">P</span></td><td>Provisional</td><td>Provisional credit for Government deductors — changes to F after PAO verification.</td></tr>
<tr><td style="text-align:center"><span class="st st-F">F</span></td><td>Final ✅</td><td>Payment matched and verified. <strong>Eligible for tax credit.</strong></td></tr>
<tr class="alt"><td style="text-align:center"><span class="st st-O">O</span></td><td>Overbooked</td><td>Amount over-claimed. Credit becomes Final only after deductor corrects.</td></tr>
<tr><td style="text-align:center"><span class="st st-Z">Z</span></td><td>Mismatch</td><td>Challan details do not match OLTAS. Updated to M once corrected.</td></tr>
<tr><td colspan="3" class="leg-title" style="font-size:13px;font-weight:700;padding:8px 10px;background:#1a5c32;color:#fff">Remarks — Legend</td></tr>
<tr><th>Code</th><th colspan="2">Description</th></tr>
<tr class="alt"><td style="text-align:center"><span class="rmk">A</span></td><td colspan="2">Rectification of error in challan uploaded by bank</td></tr>
<tr><td style="text-align:center"><span class="rmk rmk-B">B</span></td><td colspan="2">Rectification of error in statement uploaded by deductor</td></tr>
<tr class="alt"><td style="text-align:center"><span class="rmk">D</span></td><td colspan="2">Rectification of error in Form 24G filed by Accounts Officer</td></tr>
<tr><td style="text-align:center"><span class="rmk">E</span></td><td colspan="2">Rectification of error in challan by Assessing Officer</td></tr>
<tr class="alt"><td style="text-align:center"><span class="rmk">F</span></td><td colspan="2">Lower / No deduction certificate u/s 197</td></tr>
<tr><td style="text-align:center"><span class="rmk rmk-G">G</span></td><td colspan="2">Reprocessing of statement — reversal / correction entry (amounts typically negative)</td></tr>
<tr class="alt"><td style="text-align:center"><span class="rmk">T</span></td><td colspan="2">Transporter</td></tr>
</table>
</div>
"""


def _build_html(parsed: dict, row_ids: dict, report_ts: str = "") -> str:
    header = parsed["header"]
    parts  = parsed["parts"]

    pan  = header.get("Permanent Account Number (PAN)", "")
    name = header.get("Name of Assessee", "")
    fy   = header.get("Financial Year", "")
    ay   = header.get("Assessment Year", "") or header.get("Tax Year", "")

    is_168       = bool(header.get("Tax Year"))
    form_label   = "Form 168" if is_168 else "Form 26AS"
    year_prefix  = "TY" if is_168 else "AY"
    year_row_lbl = "Tax Year" if is_168 else "Assessment Year"
    _fy_row      = "" if is_168 else f'<tr class="alt"><td class="label">Financial Year</td><td>{fy}</td></tr>'
    pan_status = header.get("Current Status of PAN", "")
    gen_date   = header.get("File Creation Date", datetime.today().strftime("%d-%m-%Y"))
    if not report_ts:
        report_ts = datetime.now().strftime("%d-%b-%Y %I:%M %p")

    # Form 26AS: address split across Address Line 1-5 + Statecode + Pin Code
    # Form 168: single "Address of Assessee" field
    addr_parts = [header.get(f"Address Line {i}", "") for i in range(1, 6)]
    state = header.get("Statecode", "")
    pin   = header.get("Pin Code", "")
    addr_html = "<br>".join(a for a in addr_parts if a)
    if state:
        addr_html += f"<br>{state}"
    if pin:
        addr_html += f" — {pin}"
    if not addr_html:
        addr_html = header.get("Address of Assessee", "").replace(", ", "<br>")

    # Build tabs — include Form 168 sub-parts X_A, X_B, XI alongside Form 26AS parts
    _all_part_order = ["I","II","III","IV","V","VI","VII","VIII","IX","X_A","X_B","XI"]
    active_parts = [r for r in _all_part_order if r in parts and not parts[r]["empty"]]

    tab_items = [('assessee', '📋 Assessee Details')]
    for roman in active_parts:
        tab_items.append((f"p{roman}", f"Part-{roman}"))
    tab_items.append(('summary', '🗂 Summary'))
    tab_items.append(('legends', '📖 Legends'))

    tabs_html = ""
    for i, (tid, tlabel) in enumerate(tab_items):
        active = ' active' if i == 0 else ''
        tabs_html += f'<div class="tab{active}" onclick="show(\'{tid}\')">{tlabel}</div>\n'

    tab_ids_js = "[" + ",".join(f'"{tid}"' for tid, _ in tab_items) + "]"

    # Assessee sheet
    assessee_html = f"""
<div id="sheet-assessee" class="sheet active">
  <div class="brand">
    <div><div class="brand-title">AayDoc Capio</div>
    <div class="brand-sub">Annual Tax Statement — {form_label} · {year_prefix} {ay}</div></div>
    <div class="brand-badge">Generated by AayDoc Capio · {report_ts}</div>
  </div>
  <div class="tbl-wrap">
    <table class="ass-tbl">
      <tr class="sec-hdr"><td colspan="2">ASSESSEE INFORMATION</td></tr>
      <tr><td class="label">Permanent Account Number (PAN)</td><td>{pan}</td></tr>
      <tr class="alt"><td class="label">Current Status of PAN</td>
        <td style="color:#1a5c32;font-weight:700">✅ {pan_status}</td></tr>
      <tr><td class="label">Name of Assessee</td><td>{name}</td></tr>
      {_fy_row}
      <tr><td class="label">{year_row_lbl}</td><td>{ay}</td></tr>
      <tr class="alt"><td class="label">Data Updated Till</td><td>{gen_date}</td></tr>
      <tr><td class="label">Report Generated On</td><td>{report_ts}</td></tr>
      <tr class="sec-hdr"><td colspan="2">ADDRESS</td></tr>
      <tr><td class="label">Address</td><td>{addr_html}</td></tr>
      <tr class="sec-hdr"><td colspan="2">NOTES</td></tr>
      <tr><td colspan="2" style="color:#555;font-size:11px;padding:6px 10px">
        · All amounts in INR<br>
        · Only <strong>Final (F)</strong> status bookings are eligible for tax credit.
          Rows with other statuses (U/M/O/Z/P) are highlighted red.<br>
        · Parts VII, VIII and IX are informational only — not included in Summary.<br>
        · Figures in brackets represent reversal entries (Remarks G/B).
      </td></tr>
    </table>
  </div>
</div>"""

    # Part sheets
    part_sheets_html = ""
    part_builders = {
        "I":   lambda pd: _html_part_I_VI("I",   pd, row_ids),
        "II":  lambda pd: _html_part_II(pd, row_ids),
        "III": lambda pd: _html_part_III(pd, row_ids),
        "IV":  lambda pd: _html_part_IV_VIII("IV",  pd, row_ids),
        "V":   lambda pd: _html_part_V(pd, row_ids),
        "VI":  lambda pd: _html_part_I_VI("VI",  pd, row_ids),
        "VII": lambda pd: _html_part_VII(pd),
        "VIII":lambda pd: _html_part_IV_VIII("VIII", pd, row_ids),
        "IX":  lambda pd: _html_part_IX(pd, row_ids),
    }
    for roman in active_parts:
        pdata   = parts[roman]
        meta    = PART_META.get(roman, {})
        title   = meta.get("title", f"Part-{roman}")
        sheet_id = f"p{roman}"
        body = part_builders[roman](pdata)
        part_sheets_html += (
            f'\n<div id="sheet-{sheet_id}" class="sheet">\n'
            f'  <div class="freeze-bar">Part-{roman} — {title}</div>\n'
            f'  {body}\n'
            f'</div>\n'
        )

    # Summary sheet
    summary_body = _html_summary(parsed, row_ids)
    summary_sheet = f'\n<div id="sheet-summary" class="sheet">\n{summary_body}\n</div>\n'

    # Legends sheet
    legends_sheet = f'\n<div id="sheet-legends" class="sheet">\n{_LEGENDS_HTML}\n</div>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{form_label} — {name} — {year_prefix} {ay}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="tab-bar">
{tabs_html}</div>
{assessee_html}
{part_sheets_html}
{summary_sheet}
{legends_sheet}
<div class="footer">
  <span class="footer-copy">© 2026 AayDoc Capio™. All rights reserved. Developed by CA. Deepak Bhholusaria.</span>
  <a href="https://www.linkedin.com/in/bhholusaria/" target="_blank">🔗 linkedin.com/in/bhholusaria</a>
  <a href="mailto:deepak@ailearrning.guru">✉ deepak@ailearrning.guru</a>
</div>
<script>
const TAB_IDS = {tab_ids_js};
{_JS}
</script>
</body>
</html>"""


# ── Excel writer ──────────────────────────────────────────────────────────────

def _safe_move(tmp_path: str, xlsx_path: str) -> str:
    """Move tmp_path → xlsx_path. On PermissionError (file open in Excel)
    rename to a timestamped alternative. Returns the final path."""
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


def _write_xlsx(parsed: dict, row_ids: dict, xlsx_path: str, report_ts: str = "") -> str:
    """Returns the actual path the file was saved to (may differ if original was locked).
    Uses xlsxwriter for streaming writes — handles 200K+ row files efficiently.
    """
    import tempfile
    import xlsxwriter

    header = parsed["header"]
    parts  = parsed["parts"]

    ay            = header.get("Assessment Year", "") or header.get("Tax Year", "")
    assessee_name = header.get("Name of Assessee", "")
    assessee_pan  = header.get("Permanent Account Number (PAN)", "")

    is_168_xl      = bool(header.get("Tax Year"))
    form_label_xl  = "Form 168" if is_168_xl else "Form 26AS"
    year_prefix_xl = "TY" if is_168_xl else "AY"
    yr_row_lbl_xl  = "Tax Year" if is_168_xl else "Assessment Year"

    # xlsxwriter writes directly to a file path — use a temp file then move
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".xlsx", dir=os.path.dirname(xlsx_path) or ".")
    os.close(tmp_fd)

    wb = xlsxwriter.Workbook(tmp_path, {
        "strings_to_numbers": False,
        "strings_to_formulas": True,
        "constant_memory": False,   # keep in RAM for random-access sheet writes
        "default_date_format": "dd-mmm-yyyy",
    })

    # ── Colour constants (xlsxwriter uses HTML hex without FF prefix) ──────
    NAVY   = "#0A1628"
    GREEN  = "#1a5c32"
    SUBTTL = "#d0e8c8"
    RED_BG = "#fff0f0"
    RED_FG = "#880000"
    LABEL  = "#f0f4f0"
    WHITE  = "#ffffff"
    GREY   = "#94A3B8"
    LINK_C = "#1155CC"
    GREEN_NUM = "#7fff8a"
    GREEN_TXT = "#1a3a22"

    # ── Format factory — create once, reuse everywhere ─────────────────────
    def _fmt(bold=False, size=10, color="#000000", italic=False,
             bg=None, align="left", valign="vcenter", wrap=False,
             num_fmt=None, border=1, border_color="#D0D0D0",
             top_color=None, underline=False):
        d = {
            "font_name": "Calibri", "font_size": size,
            "bold": bold, "italic": italic,
            "font_color": color,
            "align": align, "valign": valign,
            "text_wrap": wrap,
            "left": border,   "right": border,
            "top": border,    "bottom": border,
            "left_color": border_color, "right_color": border_color,
            "top_color":  top_color or border_color,
            "bottom_color": border_color,
        }
        if bg:    d["bg_color"] = bg
        if num_fmt: d["num_format"] = num_fmt
        if underline: d["underline"] = 1
        return wb.add_format(d)

    # Pre-build all formats used in data rows (minimise add_format calls)
    F_DEFAULT   = _fmt()
    F_BOLD      = _fmt(bold=True)
    F_HDR       = _fmt(bold=True, color=WHITE, bg=GREEN, align="center")
    F_SUBTOTAL  = _fmt(bold=True, color=GREEN_TXT, bg=SUBTTL, align="right",
                       top_color=GREEN, border=1)
    F_GRANDTOT  = _fmt(bold=True, color=WHITE, bg=NAVY, align="right")
    F_GRANDNUM  = _fmt(bold=True, color=GREEN_NUM, bg=NAVY, align="right",
                       num_fmt="#,##0.00")
    F_NONFIN    = _fmt(color=RED_FG, bg=RED_BG)
    F_NONFIN_NUM= _fmt(color=RED_FG, bg=RED_BG, align="right", num_fmt="#,##0.00")
    F_NUM       = _fmt(align="right", num_fmt="#,##0.00")
    F_NUM_BOLD  = _fmt(bold=True, color=GREEN_TXT, bg=SUBTTL, align="right",
                       num_fmt="#,##0.00", top_color=GREEN)
    F_LABEL     = _fmt(bold=True, bg=LABEL)
    F_SECTION   = _fmt(bold=True, color=WHITE, bg=GREEN)
    F_NOTES     = _fmt(size=10, bg="#fffde7", valign="top", wrap=True)
    F_LINK      = _fmt(color=LINK_C, underline=True)
    F_NAVY_BOLD = _fmt(bold=True, color=WHITE, bg=NAVY)
    F_NAVY_CTR  = _fmt(bold=True, color=WHITE, bg=NAVY, align="center")
    F_BRAND_L   = _fmt(bold=True, size=10, color=WHITE, bg=NAVY, align="left")
    F_BRAND_R   = _fmt(size=8, color=GREY, bg=NAVY, align="right")
    F_TITLE     = _fmt(bold=True, size=13, color=WHITE, bg=NAVY, align="center")
    F_SUBTITLE  = _fmt(size=8, color=GREY, bg=NAVY, align="center", wrap=True)
    F_SUBTOT_LABEL = _fmt(bold=True, color=GREEN_TXT, bg=SUBTTL, align="right",
                          top_color=GREEN)
    F_GRAND_LABEL  = _fmt(bold=True, color=WHITE, bg=NAVY, align="right")

    # ── Helpers ────────────────────────────────────────────────────────────
    def _brand_row(ws, ncols, assessee=""):
        """Row 0 (xlsxwriter 0-indexed): left title | right branding, navy bg."""
        split = min(3, ncols - 1) if ncols > 1 else 0  # 0-indexed col
        ws.merge_range(0, 0, 0, split,
                       f"{form_label_xl}  —  {assessee}  —  {year_prefix_xl} {ay}", F_BRAND_L)
        if split + 1 < ncols:
            ws.merge_range(0, split + 1, 0, ncols - 1,
                           f"AayDoc Capio™  ·  {report_ts}  ·  © 2026  ·  CA. Deepak Bhholusaria",
                           F_BRAND_R)
        elif split + 1 == ncols - 1:
            ws.write(0, ncols - 1,
                     f"AayDoc Capio™  ·  {report_ts}  ·  © 2026  ·  CA. Deepak Bhholusaria",
                     F_BRAND_R)
        ws.set_row(0, 16)

    def _hdr_row(ws, cols, row=1):
        for c, h in enumerate(cols):
            ws.write(row, c, h, F_HDR)
        ws.set_row(row, 15)

    def _autofit(ws, col_data):
        """col_data: list of max-char-widths per column (0-indexed)."""
        for ci, w in enumerate(col_data):
            ws.set_column(ci, ci, min(max(w + 2, 8), 52))

    def _col_tracker(ncols):
        """Returns a list to track max content width per column."""
        return [8] * ncols

    def _track(widths, col, val):
        if val:
            widths[col] = max(widths[col], len(str(val)))

    def _ws(name, tab="#1a5c32"):
        w = wb.add_worksheet(name)
        w.set_tab_color(tab)
        return w

    def _subtotal_row(ws, row, ncols, label, num_cols, detail_start, detail_end, nf=False):
        """Write subtotal with SUM formulas. num_cols = list of 0-indexed col indices."""
        merge_to = min(ncols - len(num_cols) - 1, ncols - 1)
        if merge_to > 0:
            ws.merge_range(row, 0, row, merge_to, label, F_SUBTOT_LABEL)
        else:
            ws.write(row, 0, label, F_SUBTOT_LABEL)
        for ci in range(ncols):
            if ci in num_cols:
                if detail_start <= detail_end:
                    ws.write_formula(row, ci,
                        f"=SUM({_cl(ci)}{detail_start+1}:{_cl(ci)}{detail_end+1})",
                        F_NUM_BOLD)
                else:
                    ws.write(row, ci, 0, F_NUM_BOLD)
            elif ci > merge_to:
                ws.write(row, ci, "", F_SUBTOTAL)
        ws.set_row(row, 14)

    def _grandtotal_row(ws, row, ncols, label, num_cols, sub_rows):
        """Grand total row summing subtotal rows. sub_rows = list of 0-indexed row nums."""
        merge_to = min(ncols - len(num_cols) - 1, ncols - 1)
        if merge_to > 0:
            ws.merge_range(row, 0, row, merge_to, label, F_GRAND_LABEL)
        else:
            ws.write(row, 0, label, F_GRAND_LABEL)
        for ci in range(ncols):
            if ci in num_cols:
                if sub_rows:
                    refs = "+".join(f"{_cl(ci)}{sr+1}" for sr in sub_rows)
                    ws.write_formula(row, ci, f"={refs}", F_GRANDNUM)
                else:
                    ws.write(row, ci, 0, F_GRANDNUM)
            elif ci > merge_to:
                ws.write(row, ci, "", F_GRANDTOT)
        ws.set_row(row, 14)

    def _cl(col_idx):
        """0-indexed column index → Excel letter (A, B, ... Z, AA ...)."""
        result = ""
        n = col_idx + 1
        while n:
            n, r = divmod(n - 1, 26)
            result = chr(65 + r) + result
        return result

    # ── Assessee Details sheet ─────────────────────────────────────────────
    ws_ass = _ws("Assessee Details")
    ws_ass.merge_range(0, 0, 0, 1,
                       f"{form_label_xl}  —  {assessee_name}  —  {year_prefix_xl} {ay}", F_TITLE)
    ws_ass.set_row(0, 28)
    ws_ass.merge_range(1, 0, 1, 1,
                       "AayDoc Capio™  ·  © 2026  ·  Developed by CA. Deepak Bhholusaria  ·  linkedin.com/in/bhholusaria  ·  deepak@ailearrning.guru",
                       F_SUBTITLE)
    ws_ass.set_row(1, 22)

    fields_map = [
        ("ASSESSEE INFORMATION", None),
        ("Permanent Account Number (PAN)", "Permanent Account Number (PAN)"),
        ("Current Status of PAN",          "Current Status of PAN"),
        ("Name of Assessee",               "Name of Assessee"),
        *([("Financial Year", "Financial Year")] if not is_168_xl else []),
        (yr_row_lbl_xl,                    "Assessment Year" if not is_168_xl else "Tax Year"),
        ("Data Updated Till",              "File Creation Date"),
        ("Report Generated On",            "__report_ts__"),
        ("ADDRESS", None),
        *([("Address Line 1",  "Address Line 1"),
           ("Address Line 2",  "Address Line 2"),
           ("Address Line 3",  "Address Line 3"),
           ("Address Line 4",  "Address Line 4"),
           ("Address Line 5",  "Address Line 5"),
           ("State",           "Statecode"),
           ("PIN Code",        "Pin Code")] if not is_168_xl else [
           ("Address",         "Address of Assessee")]),
    ]
    r = 2  # 0-indexed
    for label, key in fields_map:
        if key is None:
            ws_ass.merge_range(r, 0, r, 1, label, F_SECTION)
        else:
            ws_ass.write(r, 0, label, F_LABEL)
            val = report_ts if key == "__report_ts__" else header.get(key, "")
            ws_ass.write(r, 1, val, F_DEFAULT)
        r += 1

    ws_ass.set_column(0, 0, 35)
    ws_ass.set_column(1, 1, 48)

    # Notes
    ws_ass.merge_range(r, 0, r, 1, "NOTES", F_SECTION)
    r += 1
    notes = (
        "· All amounts in INR\n"
        "· Only Final (F) status bookings are eligible for tax credit. "
        "Rows with other statuses (U/M/O/Z/P) are highlighted red.\n"
        "· Parts VII, VIII and IX are informational only — not included in Summary.\n"
        "· Figures in brackets represent reversal entries (Remarks G/B)."
    )
    ws_ass.merge_range(r, 0, r, 1, notes, F_NOTES)
    ws_ass.set_row(r, 60)

    # ── Generic deductor+detail part writer ───────────────────────────────
    def write_deductor_part(roman, cols, num_col_indices,
                            get_name, get_tan, get_detail_vals,
                            detail_status_key="Status of Booking"):
        """
        num_col_indices: list of 0-indexed column positions that hold numbers.
        get_detail_vals: fn(ded, detail) -> list of (col_0idx, value, is_num)
        """
        pdata  = parts[roman]
        ncols  = len(cols)
        num_set = set(num_col_indices)
        ws = _ws(f"Part-{roman}")
        widths = _col_tracker(ncols)

        _brand_row(ws, ncols, assessee=assessee_name)
        _hdr_row(ws, cols, row=1)
        for ci, h in enumerate(cols):
            _track(widths, ci, h)
        ws.freeze_panes(2, 0)

        r = 2  # 0-indexed; data starts at row index 2 (Excel row 3)
        sr = 0
        subtotal_rows = []

        for ded in pdata["rows"]:
            sr += 1
            name    = get_name(ded)
            tan     = get_tan(ded)
            details = ded.get("_details", [])
            row_ids[roman][sr] = {"name": name, "tan": tan, "xl_row": r + 1}  # 1-indexed for formulas
            detail_start = r
            has_nf = _non_final_class(details)

            for d in details:
                status = d.get(detail_status_key, "").strip()
                nf = status in NON_FINAL_STATUSES
                vals = get_detail_vals(ded, d)
                for ci, val, is_num in vals:
                    _track(widths, ci, val)
                    if is_num:
                        ws.write(r, ci, val or 0, F_NONFIN_NUM if nf else F_NUM)
                    else:
                        ws.write(r, ci, str(val) if val is not None else "",
                                 F_NONFIN if nf else F_DEFAULT)
                r += 1

            detail_end = r - 1
            nf_warn = " ⚠" if has_nf else ""
            label = f"Sr. {sr}  ·  Subtotal — {name}{nf_warn}"
            _track(widths, 0, label)
            _subtotal_row(ws, r, ncols, label, num_col_indices, detail_start, detail_end)
            row_ids[roman][sr]["xl_subtot"] = r + 1  # 1-indexed subtotal row for summary formulas
            subtotal_rows.append(r)
            r += 1

        # Grand total
        _grandtotal_row(ws, r, ncols, f"GRAND TOTAL — Part-{roman}",
                        num_col_indices, subtotal_rows)
        _autofit(ws, widths)

    # ── Part-I and Part-VI ─────────────────────────────────────────────────
    for roman in ["I", "VI"]:
        if roman not in parts or parts[roman]["empty"]:
            continue
        is_VI = roman == "VI"
        if is_VI:
            cols = ["Collector Name", "TAN", "Section", "Transaction Date",
                    "Booking Status", "Remarks",
                    "Total Amount Paid/Debited (Rs.)", "Tax Collected (Rs.)", "TCS Deposited (Rs.)"]
        else:
            cols = ["Deductor Name", "TAN", "Section", "Transaction Date",
                    "Booking Status", "Remarks",
                    "Amount Paid/Credited (Rs.)", "Tax Deducted (Rs.)", "TDS Deposited (Rs.)"]

        def _dv(ded, d, _is_VI=is_VI):
            status = d.get("Status of Booking", "").strip()
            rmk    = d.get("Remarks", "")
            amt_k  = "Amount Paid / Debited(Rs.)" if _is_VI else "Amount Paid / Credited(Rs.)"
            tds_k  = "Tax Collected(Rs.)"          if _is_VI else "Tax Deducted(Rs.)"
            dep_k  = "TCS Deposited(Rs.)"          if _is_VI else "TDS Deposited(Rs.)"
            name = ded.get("Name of Deductor") or ded.get("Name of Collector") or ""
            tan  = ded.get("TAN of Deductor")  or ded.get("TAN of Collector")  or ""
            return [
                (0, name, False), (1, tan, False),
                (2, d.get("Section",""), False),
                (3, d.get("Transaction Date",""), False),
                (4, STATUS_FULL.get(status, status), False),
                (5, rmk if rmk and rmk != "-" else "", False),
                (6, _fmt_num(d.get(amt_k,""))  or 0, True),
                (7, _fmt_num(d.get(tds_k,""))  or 0, True),
                (8, _fmt_num(d.get(dep_k,""))  or 0, True),
            ]

        write_deductor_part(
            roman, cols, [6, 7, 8],
            get_name=lambda d: d.get("Name of Deductor") or d.get("Name of Collector") or "",
            get_tan =lambda d: d.get("TAN of Deductor")  or d.get("TAN of Collector")  or "",
            get_detail_vals=_dv,
        )

    # ── Part-II ────────────────────────────────────────────────────────────
    if "II" in parts and not parts["II"]["empty"]:
        cols2 = ["Deductor Name", "TAN", "Section", "Transaction Date",
                 "Date of Booking", "Remarks",
                 "Amount Paid/Credited (Rs.)", "Tax Deducted (Rs.)", "TDS Deposited (Rs.)"]
        def _dv2(ded, d):
            rmk = d.get("Remarks", "")
            return [
                (0, ded.get("Name of Deductor",""), False),
                (1, ded.get("TAN of Deductor",""), False),
                (2, d.get("Section",""), False),
                (3, d.get("Transaction Date",""), False),
                (4, d.get("Date of Booking",""), False),
                (5, rmk if rmk and rmk != "-" else "", False),
                (6, _fmt_num(d.get("Amount Paid / Credited(Rs.)","")) or 0, True),
                (7, _fmt_num(d.get("Tax Deducted(Rs.)",""))            or 0, True),
                (8, _fmt_num(d.get("TDS Deposited(Rs.)",""))           or 0, True),
            ]
        write_deductor_part("II", cols2, [6, 7, 8],
            get_name=lambda d: d.get("Name of Deductor",""),
            get_tan =lambda d: d.get("TAN of Deductor",""),
            get_detail_vals=_dv2)

    # ── Part-III ───────────────────────────────────────────────────────────
    if "III" in parts and not parts["III"]["empty"]:
        cols3 = ["Deductor Name", "TAN", "Section", "Transaction Date",
                 "Booking Status", "Remarks", "Amount Paid/Credited (Rs.)"]
        def _dv3(ded, d):
            status = d.get("Status of Booking","").strip()
            rmk = d.get("Remarks","")
            return [
                (0, ded.get("Name of Deductor",""), False),
                (1, ded.get("TAN of Deductor",""), False),
                (2, d.get("Section",""), False),
                (3, d.get("Transaction Date",""), False),
                (4, STATUS_FULL.get(status, status), False),
                (5, rmk if rmk and rmk != "-" else "", False),
                (6, _fmt_num(d.get("Amount Paid / Credited(Rs.)","")) or 0, True),
            ]
        write_deductor_part("III", cols3, [6],
            get_name=lambda d: d.get("Name of Deductor",""),
            get_tan =lambda d: d.get("TAN of Deductor",""),
            get_detail_vals=_dv3)

    # ── Part-IV and Part-VIII ──────────────────────────────────────────────
    for roman in ["IV", "VIII"]:
        if roman not in parts or parts[roman]["empty"]:
            continue
        is_VIII = roman == "VIII"
        if is_VIII:
            cols = ["Name of Deductee", "PAN of Deductee", "Ack. No.", "TDS Cert. No.",
                    "Section", "Transaction Date", "Date of Deposit", "Booking Status",
                    "Demand Payment", "Total Transaction Amount (Rs.)",
                    "TDS Deposited (Rs.)", "Other Amount (Rs.)"]
            name_key, pan_key = "Name of Deductee", "PAN of Deductee"
            num_cols = [9, 10, 11]
        else:
            cols = ["Name of Deductor (Buyer)", "PAN of Deductor", "Ack. No.", "TDS Cert. No.",
                    "Section", "Transaction Date", "Date of Deposit", "Booking Status",
                    "Demand Payment", "Total Transaction Amount (Rs.)", "TDS Deposited (Rs.)"]
            name_key, pan_key = "Name of Deductor", "PAN of Deductor"
            num_cols = [9, 10]

        ncols  = len(cols)
        pdata  = parts[roman]
        ws     = _ws(f"Part-{roman}")
        widths = _col_tracker(ncols)

        _brand_row(ws, ncols, assessee=assessee_name)
        _hdr_row(ws, cols, row=1)
        ws.freeze_panes(2, 0)

        r = 2; sr = 0; subtotal_rows = []
        for ded in pdata["rows"]:
            sr += 1
            name   = (ded.get(name_key) or ded.get("Name of Deductor") or "").strip()
            pan    = (ded.get(pan_key)  or ded.get("PAN of Deductor")  or "").strip()
            ack    = ded.get("Acknowledgement Number", "")
            txdate = ded.get("Transaction Date", "")
            txamt  = _fmt_num(ded.get("Total Transaction Amount(Rs.)","")) or 0
            details = ded.get("_details", [])
            row_ids[roman][sr] = {"name": name, "tan": pan, "xl_row": r + 1}
            detail_start = r

            for d in details:
                status = d.get("Status of Booking","").strip()
                nf = status in NON_FINAL_STATUSES
                sf, nf_ = (F_NONFIN, F_NONFIN_NUM) if nf else (F_DEFAULT, F_NUM)
                ws.write(r, 0, name, sf);   ws.write(r, 1, pan, sf)
                ws.write(r, 2, ack, sf);    ws.write(r, 3, d.get("TDS Certificate Number",""), sf)
                ws.write(r, 4, d.get("Section",""), sf)
                ws.write(r, 5, txdate, sf); ws.write(r, 6, d.get("Date of Deposit",""), sf)
                ws.write(r, 7, STATUS_FULL.get(status, status), sf)
                ws.write(r, 8, d.get("Demand Payment",""), sf)
                ws.write(r, 9, txamt, nf_)
                ws.write(r, 10, _fmt_num(d.get("TDS Deposited(Rs.)","")) or 0, nf_)
                if is_VIII:
                    ws.write(r, 11, _fmt_num(d.get("Total Amount Deposited other than TDS(Rs.)","")) or 0, nf_)
                _track(widths, 0, name)
                r += 1

            detail_end = r - 1
            label = f"Sr. {sr}  ·  Subtotal — {name}"
            _subtotal_row(ws, r, ncols, label, num_cols, detail_start, detail_end)
            row_ids[roman][sr]["xl_subtot"] = r + 1  # 1-indexed subtotal row for summary formulas
            subtotal_rows.append(r); r += 1

        _grandtotal_row(ws, r, ncols, f"GRAND TOTAL — Part-{roman}",
                        num_cols, subtotal_rows)
        for ci, h in enumerate(cols): _track(widths, ci, h)
        _autofit(ws, widths)

    # ── Part-V ─────────────────────────────────────────────────────────────
    if "V" in parts and not parts["V"]["empty"]:
        pdata  = parts["V"]
        cols5  = ["Name of Buyer", "PAN of Buyer", "Ack. No.", "Transaction Date",
                  "Total Transaction Amount (Rs.)", "BSR Code", "Date of Deposit",
                  "Challan Serial No.", "Total Tax Amount (Rs.)", "Booking Status", "Demand Payment"]
        ncols5 = len(cols5)
        ws5    = _ws("Part-V")
        w5     = _col_tracker(ncols5)

        _brand_row(ws5, ncols5, assessee=assessee_name)
        _hdr_row(ws5, cols5, row=1)
        ws5.freeze_panes(2, 0)

        r = 2; sr = 0; sub5 = []
        for ded in pdata["rows"]:
            sr += 1
            name   = ded.get("Name of Buyer","");  pan   = ded.get("PAN of Buyer","")
            ack    = ded.get("Acknowledgement Number","")
            txdate = ded.get("Transaction Date","")
            txamt  = _fmt_num(ded.get("Total Transaction Amount(Rs.)","")) or 0
            details = ded.get("_details",[])
            row_ids["V"][sr] = {"name": name, "tan": pan, "xl_row": r + 1}
            detail_start = r
            for d in details:
                status = d.get("Status of Booking","").strip()
                nf = status in NON_FINAL_STATUSES
                sf, nf_ = (F_NONFIN, F_NONFIN_NUM) if nf else (F_DEFAULT, F_NUM)
                ws5.write(r, 0, name, sf);  ws5.write(r, 1, pan, sf)
                ws5.write(r, 2, ack, sf);   ws5.write(r, 3, txdate, sf)
                ws5.write(r, 4, txamt, nf_)
                ws5.write(r, 5, d.get("BSR Code",""), sf)
                ws5.write(r, 6, d.get("Date of Deposit",""), sf)
                ws5.write(r, 7, d.get("Challan Serial Number","") or d.get("Challan Serial No.",""), sf)
                ws5.write(r, 8, _fmt_num(d.get("Total Tax Amount(Rs.)","")) or 0, nf_)
                ws5.write(r, 9, STATUS_FULL.get(status, status), sf)
                ws5.write(r, 10, d.get("Demand Payment",""), sf)
                _track(w5, 0, name); r += 1
            detail_end = r - 1
            _subtotal_row(ws5, r, ncols5, f"Sr. {sr}  ·  Subtotal — {name}",
                          [4, 8], detail_start, detail_end)
            row_ids["V"][sr]["xl_subtot"] = r + 1  # 1-indexed subtotal row for summary formulas
            sub5.append(r); r += 1
        _grandtotal_row(ws5, r, ncols5, "GRAND TOTAL — Part-V", [4, 8], sub5)
        for ci, h in enumerate(cols5): _track(w5, ci, h)
        _autofit(ws5, w5)

    # ── Part-VII ───────────────────────────────────────────────────────────
    if "VII" in parts and not parts["VII"]["empty"]:
        pdata7 = parts["VII"]
        cols7  = ["Assessment Year", "Mode", "Refund Issued", "Nature of Refund",
                  "Amount of Refund (Rs.)", "Interest (Rs.)", "Date of Payment", "Remarks"]
        ncols7 = len(cols7)
        ws7    = _ws("Part-VII")
        w7     = _col_tracker(ncols7)

        _brand_row(ws7, ncols7, assessee=assessee_name)
        _hdr_row(ws7, cols7, row=1)
        ws7.freeze_panes(2, 0)

        r = 2
        for ded in pdata7["rows"]:
            rmk = ded.get("Remarks","")
            ws7.write(r, 0, ded.get("Assessment Year",""), F_DEFAULT)
            ws7.write(r, 1, ded.get("Mode",""), F_DEFAULT)
            ws7.write(r, 2, ded.get("Refund Issued",""), F_DEFAULT)
            ws7.write(r, 3, ded.get("Nature of Refund",""), F_DEFAULT)
            ws7.write(r, 4, _fmt_num(ded.get("Amount of Refund(Rs.)","")) or 0, F_NUM)
            ws7.write(r, 5, _fmt_num(ded.get("Interest(Rs.)","")) or 0, F_NUM)
            ws7.write(r, 6, ded.get("Date of Payment",""), F_DEFAULT)
            ws7.write(r, 7, rmk if rmk != "-" else "", F_DEFAULT)
            for ci, h in enumerate(cols7): _track(w7, ci, h)
            r += 1
        _autofit(ws7, w7)

    # ── Part-IX ────────────────────────────────────────────────────────────
    if "IX" in parts and not parts["IX"]["empty"]:
        pdata9 = parts["IX"]
        cols9  = ["Name of Seller", "PAN of Seller", "Ack. No.", "Transaction Date",
                  "Total Transaction Amount (Rs.)", "BSR Code", "Date of Deposit",
                  "Challan Serial No.", "Total Tax Amount (Rs.)", "Booking Status",
                  "Demand Payment", "Other Amount Deposited (Rs.)"]
        ncols9 = len(cols9)
        ws9    = _ws("Part-IX")
        w9     = _col_tracker(ncols9)

        _brand_row(ws9, ncols9, assessee=assessee_name)
        _hdr_row(ws9, cols9, row=1)
        ws9.freeze_panes(2, 0)

        r = 2; sr = 0
        for ded in pdata9["rows"]:
            sr += 1
            name   = ded.get("Name of Seller","");  pan   = ded.get("PAN of Seller","")
            ack    = ded.get("Acknowledgement Number","")
            txdate = ded.get("Transaction Date","")
            txamt  = _fmt_num(ded.get("Total Transaction Amount(Rs.)","")) or 0
            row_ids["IX"][sr] = {"name": name, "tan": pan, "xl_row": r + 1}
            for d in ded.get("_details",[]):
                status = d.get("Status of Booking","").strip()
                nf = status in NON_FINAL_STATUSES
                sf, nf_ = (F_NONFIN, F_NONFIN_NUM) if nf else (F_DEFAULT, F_NUM)
                ws9.write(r, 0, name, sf);   ws9.write(r, 1, pan, sf)
                ws9.write(r, 2, ack, sf);    ws9.write(r, 3, txdate, sf)
                ws9.write(r, 4, txamt, nf_)
                ws9.write(r, 5, d.get("BSR Code",""), sf)
                ws9.write(r, 6, d.get("Date of Deposit",""), sf)
                ws9.write(r, 7, d.get("Challan Serial Number","") or d.get("Challan Serial No.",""), sf)
                ws9.write(r, 8, _fmt_num(d.get("Total Tax Amount(Rs.)","")) or 0, nf_)
                ws9.write(r, 9, STATUS_FULL.get(status, status), sf)
                ws9.write(r, 10, d.get("Demand Payment",""), sf)
                ws9.write(r, 11, _fmt_num(d.get("Total Amount Deposited other than TDS(Rs.)","")) or 0, nf_)
                _track(w9, 0, name); r += 1
        for ci, h in enumerate(cols9): _track(w9, ci, h)
        _autofit(ws9, w9)

    # ── Summary sheet ──────────────────────────────────────────────────────
    sum_cols  = ["Part", "Part Title", "Deductor / Payer / Collector Name", "TAN / PAN",
                 "Total Amount (Rs.)", "Tax Deducted/Collected (Rs.)", "Tax Deposited (Rs.)",
                 "Non-Final Rows"]
    ncols_sum = len(sum_cols)
    ws_sum    = _ws("Summary")
    w_sum     = _col_tracker(ncols_sum)

    _brand_row(ws_sum, ncols_sum, assessee=assessee_name)
    _hdr_row(ws_sum, sum_cols, row=1)
    ws_sum.freeze_panes(2, 0)
    r = 2

    # Column indices (0-based) for (amount, tds/tcs, deposited) per Part sheet
    PART_AMT_COLS = {
        "I":   (6, 7, 8),
        "II":  (6, 7, 8),
        "III": (6, None, None),
        "IV":  (9, None, 10),
        "V":   (4, 8, None),
        "VI":  (6, 7, 8),
    }

    credit_parts = [p for p in ["I","II","III","IV","V","VI"]
                    if p in parts and not parts[p]["empty"]]
    for roman in credit_parts:
        pdata      = parts[roman]
        meta       = PART_META.get(roman, {})
        part_label = f"Part-{roman}"
        sheet_name = f"Part-{roman}"
        acols      = PART_AMT_COLS[roman]

        for sr, info in row_ids.get(roman, {}).items():
            name    = info["name"]
            tan     = info["tan"]
            xl_row  = info.get("xl_row", 3)
            xl_subtot = info.get("xl_subtot", xl_row)

            # nf_count still requires inspecting _details
            ded_rows = _match_ded(pdata["rows"], name, tan)
            nf_count = 0
            if ded_rows:
                for d in ded_rows[0].get("_details", []):
                    if (d.get("Status of Booking") or "").strip() in NON_FINAL_STATUSES:
                        nf_count += 1

            nf = nf_count > 0
            sf, nf_ = (F_NONFIN, F_NONFIN_NUM) if nf else (F_DEFAULT, F_NUM)

            def _ref(col_idx):
                if col_idx is None:
                    return None
                return f"='{sheet_name}'!{_cl(col_idx)}{xl_subtot}"

            ws_sum.write(r, 0, part_label, F_NAVY_CTR)
            ws_sum.write(r, 1, meta.get("title",""), sf)
            ws_sum.write_url(r, 2,
                             f"internal:'{sheet_name}'!A{xl_row}",
                             F_LINK, name)
            _track(w_sum, 2, name)
            ws_sum.write_url(r, 3, f"internal:'{sheet_name}'!A{xl_row}", F_LINK, tan)
            ws_sum.write_formula(r, 4, _ref(acols[0]), nf_)
            if roman == "III":
                ws_sum.write(r, 5, "—", sf)
                ws_sum.write(r, 6, "—", sf)
            else:
                ws_sum.write_formula(r, 5, _ref(acols[1]) or '=""', nf_)
                ws_sum.write_formula(r, 6, _ref(acols[2]) or '=""', nf_)
            ws_sum.write(r, 7, str(nf_count), sf)
            r += 1

        # Part subtotal label row
        label = f"{part_label} Subtotal — {len(row_ids.get(roman, {}))} entries"
        ws_sum.merge_range(r, 0, r, 2, label, F_SUBTOT_LABEL)
        for ci in range(3, ncols_sum):
            ws_sum.write(r, ci, "", F_SUBTOTAL)
        r += 1

    # Grand total
    ws_sum.merge_range(r, 0, r, 2, "GRAND TOTAL  (Parts I–VI, credit only)", F_GRAND_LABEL)
    for ci in range(3, ncols_sum):
        ws_sum.write(r, ci, "", F_GRANDTOT)

    for ci, h in enumerate(sum_cols): _track(w_sum, ci, h)
    _autofit(ws_sum, w_sum)

    # ── File properties ────────────────────────────────────────────────────
    wb.set_properties({
        "title":    f"{form_label_xl} — {assessee_name} — {year_prefix_xl} {ay}",
        "subject":  f"Annual Tax Statement | PAN: {assessee_pan} | {year_prefix_xl}: {ay}",
        "author":   "AayDoc Capio",
        "keywords": f"{'168' if is_168_xl else '26AS'}, TDS, TCS, {assessee_pan}, {ay}",
        "comments": f"Generated by AayDoc Capio on {report_ts}",
    })

    wb.close()   # flushes and writes to tmp_path
    return _safe_move(tmp_path, xlsx_path)


# ── Public API ────────────────────────────────────────────────────────────────

def convert_26as_txt(txt_path: str, log_callback=None) -> tuple[str, str]:
    """Parse txt_path and write .xlsx + .html alongside it.
    Returns (xlsx_path, html_path).
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    base = os.path.splitext(txt_path)[0]
    xlsx_path = base + ".xlsx"
    html_path = base + ".html"

    log(f"[26AS] Parsing: {os.path.basename(txt_path)}")
    parsed = _parse(txt_path)
    report_ts = datetime.now().strftime("%d-%b-%Y %I:%M %p")

    # row_ids is filled in during HTML building, then reused for Excel
    row_ids = {r: {} for r in ["I","II","III","IV","V","VI","VII","VIII","IX","X_A","X_B","XI"]}

    log(f"[26AS] Building HTML...")
    html = _build_html(parsed, row_ids, report_ts)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"[26AS] HTML saved: {os.path.basename(html_path)}")

    # row_ids now populated with xl_row stubs (0); Excel writer fills xl_row properly
    row_ids = {r: {} for r in ["I","II","III","IV","V","VI","VII","VIII","IX","X_A","X_B","XI"]}

    log(f"[26AS] Building Excel workbook...")
    try:
        actual_xlsx = _write_xlsx(parsed, row_ids, xlsx_path, report_ts)
        if actual_xlsx != xlsx_path:
            log(f"[Warning] '{os.path.basename(xlsx_path)}' was open in Excel — "
                f"saved as '{os.path.basename(actual_xlsx)}' instead.")
        log(f"[26AS] Excel saved: {os.path.basename(actual_xlsx)}")
        xlsx_path = actual_xlsx
    except PermissionError as pe:
        log(f"[Error] Excel save failed: {pe}")
        raise

    return xlsx_path, html_path
