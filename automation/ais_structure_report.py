"""
AIS JSON Schema Reference Generator — Developer Tool

Scans ALL decrypted AIS JSON files in a folder, merges the complete schema
across all files, and produces:
  1. An interactive HTML tree (AIS_JSON_Tree.html) — collapsible, no confidential data
  2. An Excel tree-structure workbook (AIS_JSON_Schema.xlsx)

All outputs are sanitised — no real PAN, name, address, or other personal data.

Usage:
    python -m automation.ais_structure_report [folder]   # default: testdata/Decrypted JSON/
"""

import json
import sys
from pathlib import Path


# ── Placeholder map for confidential partA / metadata / footer values ─────────
_PARTA_PLACEHOLDERS = {
    "Permanent Account Number (PAN)": "AAAAA9999A",
    "Aadhaar Number":                 "XXXX XXXX XXXX",
    "Name of Assessee":               "SAMPLE ASSESSEE",
    "Date of Birth":                  "DD/MM/YYYY",
    "Mobile Number":                  "9999999999",
    "E-mail Address":                 "sample@example.com",
    "Address":                        "[Address redacted]",
}
_META_PLACEHOLDERS = {
    "loggedInPan":  "AAAAA9999A",
    "downloadDate": "DD-MMM-YYYY",
}
_FOOTER_PLACEHOLDERS = {
    "Download ID":    "[Download ID redacted]",
    "IP Address":     "[IP redacted]",
    "Generation Date":"[Date redacted]",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _col_names(label_list) -> list[str]:
    return [c.get("name", "") if isinstance(c, dict) else str(c) for c in (label_list or [])]


def _parse_l2(elem: dict) -> dict:
    l2 = elem.get("l2") or {}
    labels = _col_names(l2.get("columnLabel", []))
    rows = l2.get("columnData", [])
    row = rows[0] if rows else []
    return dict(zip(labels, row))


def _get_field(d: dict, *keys) -> str:
    for k in keys:
        v = d.get(k, "")
        if v:
            return str(v).strip()
    return ""


# ── Schema collector ───────────────────────────────────────────────────────────

def collect_schema(folder: Path) -> dict:
    """Scan all *_decrypted.json files and return merged schema (no personal data)."""
    files = sorted(folder.glob("*_decrypted.json"))
    if not files:
        raise FileNotFoundError(f"No *_decrypted.json files found in {folder}")

    print(f"Scanning {len(files)} files: {[f.name for f in files]}")

    schema = {
        "file_count": len(files),        # count only — no filenames
        "metadata_keys": [],
        "metadata_sample": {},           # sanitised sample values
        "header_labels": [],
        "partA_labels": [],
        "footer_labels": [],
        "sections": {},
    }

    for fpath in files:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)

        # metadata keys + sanitised sample
        meta = data.get("metadata", {})
        for k, v in meta.items():
            if k not in schema["metadata_keys"]:
                schema["metadata_keys"].append(k)
            if k not in schema["metadata_sample"]:
                # Use placeholder if sensitive, else use actual (non-personal) values
                schema["metadata_sample"][k] = _META_PLACEHOLDERS.get(k, repr(v))

        # header labels
        for lab in _col_names(data.get("header", {}).get("columnLabel", [])):
            if lab and lab not in schema["header_labels"]:
                schema["header_labels"].append(lab)

        # partA labels
        for lab in _col_names(data.get("partA", {}).get("columnLabel", [])):
            if lab and lab not in schema["partA_labels"]:
                schema["partA_labels"].append(lab)

        # footer labels
        for lab in _col_names(data.get("footer", {}).get("columnLabel", [])):
            if lab and lab not in schema["footer_labels"]:
                schema["footer_labels"].append(lab)

        # partB sections
        for sec in data.get("partB", {}).get("sections", []):
            sk = sec.get("sectionKey", "")
            if not sk:
                continue
            if sk not in schema["sections"]:
                schema["sections"][sk] = {
                    "title":       sec.get("title", ""),
                    "heading":     sec.get("heading", ""),
                    "elements":    {},
                    "subSections": sec.get("subSections", []),
                }
            elif not schema["sections"][sk]["title"] and sec.get("title"):
                schema["sections"][sk]["title"] = sec.get("title", "")

            for elem in (sec.get("elements") or []):
                if not elem:
                    continue
                l2 = _parse_l2(elem)
                ic   = _get_field(l2, "Information Code", "info_code")
                cat  = _get_field(l2, "Information Category", "category")
                desc = _get_field(l2, "Information Description", "description")
                src  = elem.get("l1Src") or "(none)"

                l1       = elem.get("l1") or {}
                l1_all   = _col_names(l1.get("columnLabel", []))
                l1_labels = [c for c in l1_all if c.lower() not in ("feedback", "")]
                l1_dt    = l1.get("columnDataType", [])[:len(l1_labels)]
                l1_rows  = l1.get("columnData", [])

                l2_labels = _col_names((elem.get("l2") or {}).get("columnLabel", []))
                l2_dt     = (elem.get("l2") or {}).get("columnDataType", [])

                key = ic or "(unknown)"
                elems = schema["sections"][sk]["elements"]
                if key not in elems:
                    elems[key] = {
                        "category":    cat,
                        "description": desc,
                        "l1Src":       src,
                        "l2_labels":   [],
                        "l2_dt":       [],
                        "l1_labels":   [],
                        "l1_dt":       [],
                        "row_counts":  [],
                    }
                e = elems[key]
                if cat  and not e["category"]:    e["category"]    = cat
                if desc and not e["description"]: e["description"] = desc
                if src != "(none)":               e["l1Src"]       = src
                e["row_counts"].append(len(l1_rows))
                if len(l1_labels) > len(e["l1_labels"]):
                    e["l1_labels"] = l1_labels
                    e["l1_dt"]     = l1_dt
                for lab in l2_labels:
                    if lab and lab not in e["l2_labels"]:
                        e["l2_labels"].append(lab)
                if len(l2_dt) > len(e["l2_dt"]):
                    e["l2_dt"] = l2_dt

    return schema


# ── Section / display constants ────────────────────────────────────────────────

_SECTION_DISPLAY = {
    "tdsTcs":          "Part B1 — TDS / TCS",
    "sft":             "Part B2 — Specified Financial Transactions (SFT)",
    "paymentOfTaxes":  "Part B3 — Payment of Taxes",
    "demandAndRefund": "Part B4 — Demand and Refund",
    "other-info":      "Part B7 — Other Information",
}

_L1SRC_DESC = {
    "AIS_TDS_TCS":                "Standard TDS/TCS deductions",
    "AIS_TDS_26_QB_QC_QD":        "TDS on immovable property (Form 26QB/QC/QD)",
    "AIS_TDS_ANNEX2":             "Salary — TDS Annexure II",
    "AIS_SFT_PRSN":               "SFT — person-level amounts (dividend, interest, purchases)",
    "AIS_SFT_ACNT":               "SFT — account-level (savings/deposit interest)",
    "AIS_SFT_PRPRTY":             "SFT — immovable property transactions",
    "AIS_GSTR_1_3B":              "GST returns — GSTR-1 (purchases) and GSTR-3B (sales turnover); any GST-registered assessee",
    "AIS_SEC_DEP_MF":             "Securities/MF — market sale transactions (Depository & RTA)",
    "AIS_SEC_DEP_MF_OFF":         "Securities — off-market credit transactions (Depository)",
    "AIS_SEC_DEP_MF_HLD_PUR_DIV": "Securities/MF — holding, purchase & dividend (Depository & RTA)",
    "(none)":                     "Empty / no transaction data",
}

SEC_ORDER = ["tdsTcs", "sft", "paymentOfTaxes", "demandAndRefund", "other-info"]


# ── HTML tree generator ────────────────────────────────────────────────────────

def generate_html(schema: dict, out_path: Path):
    """Generate a standalone interactive HTML file with a fully collapsible tree."""

    def h(text):
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lines = []
    a = lines.append

    a("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AIS JSON — Developer Schema Reference</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: Calibri, Arial, sans-serif; font-size: 13px;
         background: #f0f2f5; color: #111; margin: 0; padding: 0; }
  .page { max-width: 1200px; margin: 0 auto; padding: 20px 24px; }

  /* ── Header ── */
  h1 { background: #0A1628; color: #fff; padding: 14px 20px; margin: 0 0 12px;
       font-size: 16px; border-radius: 6px; }
  h1 span { color: #7fffef; font-size: 12px; font-weight: normal; margin-left: 16px; }
  .toolbar { margin-bottom: 16px; }
  .btn { background: #0E6674; color: #fff; border: none; padding: 6px 14px;
         border-radius: 4px; cursor: pointer; font-size: 12px; margin-right: 6px; }
  .btn:hover { background: #1a8a9a; }

  /* ── Tree container ── */
  .tree { background: #fff; border: 1px solid #d0e4e8; border-radius: 6px;
          padding: 8px 0; box-shadow: 0 1px 4px rgba(0,0,0,.06); }

  /* ── details / summary base ── */
  details { margin: 0; }
  details > summary {
    cursor: pointer; list-style: none; user-select: none;
    display: flex; align-items: center; gap: 6px;
    padding: 5px 12px; line-height: 1.4;
  }
  details > summary::-webkit-details-marker { display: none; }
  /* triangle icon */
  details > summary .tri { display: inline-block; width: 14px; text-align: center;
                            font-size: 9px; color: #888; flex-shrink: 0; }
  details > summary:hover .tri { color: #0E6674; }
  details[open] > summary .tri::before { content: "▼"; }
  details:not([open]) > summary .tri::before { content: "▶"; }

  /* ── Level 0: Root ── */
  .L0 { border-bottom: 2px solid #d0eef2; }
  .L0 > summary { background: #0A1628; color: #fff; font-size: 14px; font-weight: 700;
                  padding: 10px 16px; border-radius: 5px 5px 0 0; }
  .L0 > summary .tri { color: #7fffef; }
  .L0 > .children { padding-left: 0; }

  /* ── Level 1: Top-level keys (metadata, header, partA, partB, footer) ── */
  .L1 > summary { background: #0E6674; color: #fff; font-size: 13px; font-weight: 700;
                  padding: 7px 16px; border-top: 1px solid #0a5060; }
  .L1 > summary .tri { color: #d0eef2; }
  .L1 > summary:hover { background: #1a8a9a; }
  .L1 > .children { padding-left: 24px; border-left: 3px solid #0E6674;
                    margin-left: 16px; }

  /* ── Level 2: Sections within partB ── */
  .L2 > summary { background: #e8f5f7; color: #0a2d33; font-size: 12px;
                  font-weight: 700; padding: 6px 12px;
                  border-top: 1px solid #c0e0e6; }
  .L2 > summary:hover { background: #d0eef2; }
  .L2 > summary .tri { color: #0E6674; }
  .L2 > .children { padding-left: 20px; border-left: 2px solid #1a8a9a;
                    margin-left: 12px; }

  /* ── Level 3: Info code elements ── */
  .L3 > summary { background: #fff; color: #0a2d33; font-size: 12px;
                  padding: 5px 10px; border-top: 1px solid #e8f0f2; }
  .L3 > summary:hover { background: #f0fafc; }
  .L3 > summary .tri { color: #1a8a9a; }
  .L3 > .children { padding-left: 18px; border-left: 2px dashed #c0dde2;
                    margin-left: 10px; padding-top: 4px; padding-bottom: 4px; }

  /* ── Level 4: l2 / l1 sub-sections ── */
  .L4 > summary { background: #fafafa; color: #444; font-size: 11.5px;
                  font-style: italic; padding: 4px 10px;
                  border-top: 1px solid #eee; }
  .L4 > summary:hover { background: #f0f8f9; }
  .L4 > summary .tri { color: #aaa; }
  .L4 > .children { padding-left: 14px; border-left: 1px dotted #ccc;
                    margin-left: 8px; padding-top: 4px; }

  /* ── Field rows (leaf data) ── */
  .field-row { display: flex; gap: 0; padding: 3px 8px; font-size: 12px;
               border-top: 1px solid #f0f4f5; align-items: baseline; }
  .field-row:first-child { border-top: none; }
  .field-key { color: #0a2d33; font-weight: 600; min-width: 220px; flex-shrink: 0; }
  .field-val { color: #333; }
  .field-note { color: #888; font-style: italic; font-size: 11px; margin-left: 8px; }

  /* ── Tables ── */
  table { border-collapse: collapse; font-size: 12px; margin: 6px 0 8px 0;
          width: 100%; max-width: 800px; }
  th { background: #0E6674; color: #fff; padding: 5px 10px; text-align: left;
       font-size: 11.5px; }
  td { padding: 4px 10px; border: 1px solid #dde8ea; vertical-align: top; }
  tr:nth-child(even) td { background: #f4fbfc; }

  /* ── Misc ── */
  code { background: #e8f5f7; padding: 1px 5px; border-radius: 3px;
         font-size: 11px; font-family: "Courier New", monospace; }
  .badge { display: inline-block; background: #0E6674; color: #fff; border-radius: 3px;
           padding: 1px 8px; font-size: 11px; font-family: monospace; margin-right: 4px; }
  .tag  { display: inline-block; background: #e8f5f7; color: #0a2d33; border: 1px solid #b0d8de;
          border-radius: 3px; padding: 1px 6px; font-size: 10.5px; margin-left: 6px; }
  .note { color: #777; font-size: 11px; font-style: italic; padding: 3px 8px; }
  .warn { color: #8b4513; font-size: 11px; padding: 3px 8px; }
  .section-count { color: #aaa; font-size: 11px; font-weight: normal; margin-left: 8px; }
  .l1src-tag { color: #7030A0; font-size: 11px; font-family: monospace; margin-left: 6px; }
</style>
</head>
<body>
<div class="page">
""")

    def tri(): return '<span class="tri"></span>'

    a(f'<h1>AIS JSON — Developer Schema Reference '
      f'<span>{schema["file_count"]} files scanned &nbsp;·&nbsp; No confidential data</span></h1>')
    a('<div class="toolbar">')
    a('<button class="btn" onclick="toggleAll(true)">⊞ Expand All</button>')
    a('<button class="btn" onclick="toggleAll(false)">⊟ Collapse All</button>')
    a('<button class="btn" onclick="toggleLevel(1)">Level 1</button>')
    a('<button class="btn" onclick="toggleLevel(2)">Level 2</button>')
    a('<button class="btn" onclick="toggleLevel(3)">Level 3</button>')
    a('</div>')
    a('<div class="tree">')

    # ── Root ──────────────────────────────────────────────────────────────────
    a('<details class="L0" open>')
    a(f'<summary>{tri()} AIS JSON &nbsp;<span class="tag">root object</span></summary>')
    a('<div class="children">')

    # ── metadata ──────────────────────────────────────────────────────────────
    a('<details class="L1">')
    a(f'<summary>{tri()} metadata &nbsp;<span class="tag">object</span></summary>')
    a('<div class="children">')
    meta_desc = {
        "loggedInPan":  ("string", "PAN of the assessee"),
        "jsonVersion":  ("string", 'e.g. "14.0.0"'),
        "downloadDate": ("string", "DD-MMM-YYYY format"),
        "utilityVersion": ("string", "ITD utility version"),
        "sourceSharedFeedbackFeatureEnabled": ("boolean", ""),
    }
    for k in schema["metadata_keys"]:
        typ, note = meta_desc.get(k, ("varies", ""))
        sample = schema["metadata_sample"].get(k, "")
        a(f'<div class="field-row"><span class="field-key"><code>{h(k)}</code></span>'
          f'<span class="field-val">{h(typ)} = <code>{h(sample)}</code></span>'
          f'<span class="field-note">{h(note)}</span></div>')
    a('</div></details>')  # metadata

    # ── header ────────────────────────────────────────────────────────────────
    a('<details class="L1">')
    a(f'<summary>{tri()} header &nbsp;<span class="tag">object</span></summary>')
    a('<div class="children">')
    a('<div class="note">Parallel arrays: <code>title</code> · <code>columnLabel</code> · <code>columnData</code></div>')
    hdr_ex = {"Financial Year ": "2024-25", "Assessment Year ": "2025-26"}
    a('<table><tr><th>#</th><th>columnLabel</th><th>Example value</th></tr>')
    for i, lab in enumerate(schema["header_labels"], 1):
        a(f'<tr><td>{i}</td><td><code>{h(lab)}</code></td><td>{hdr_ex.get(lab,"")}</td></tr>')
    a('</table>')
    a('<div class="warn">⚠ Read FY from columnData[0] where label contains "Financial" — do NOT use metadata.downloadDate</div>')
    a('</div></details>')  # header

    # ── partA ─────────────────────────────────────────────────────────────────
    a('<details class="L1">')
    a(f'<summary>{tri()} partA — Assessee Profile &nbsp;<span class="tag">object</span></summary>')
    a('<div class="children">')
    a('<div class="note">Sub-keys: <code>heading</code> · <code>title</code> · <code>columnLabel[]</code> · <code>columnData[]</code> (single row)</div>')
    parta_notes = {
        "Permanent Account Number (PAN)": "Clear text",
        "Aadhaar Number": "Masked by ITD — last 4 digits real in JSON",
        "Name of Assessee": "Use for brand row in Excel output",
        "Date of Birth": "DD/MM/YYYY",
        "Mobile Number": "Clear text",
        "E-mail Address": "Clear text",
        "Address": "Full address string",
    }
    a('<table><tr><th>#</th><th>columnLabel</th><th>Placeholder</th><th>Notes</th></tr>')
    for i, lab in enumerate(schema["partA_labels"], 1):
        placeholder = _PARTA_PLACEHOLDERS.get(lab, "[value]")
        note = parta_notes.get(lab, "")
        a(f'<tr><td>{i}</td><td><code>{h(lab)}</code></td>'
          f'<td><code>{h(placeholder)}</code></td><td>{h(note)}</td></tr>')
    a('</table>')
    a('</div></details>')  # partA

    # ── partB ─────────────────────────────────────────────────────────────────
    a('<details class="L1" open>')
    a(f'<summary>{tri()} partB — Information by Source &nbsp;<span class="tag">object</span></summary>')
    a('<div class="children">')
    a('<div class="note">Keys: <code>title</code> · <code>lastFeedbackMap</code> (internal) · <code>sections[]</code></div>')

    for sk in SEC_ORDER:
        if sk not in schema["sections"]:
            continue
        sec = schema["sections"][sk]
        display = _SECTION_DISPLAY.get(sk, sk)
        elements = {k: v for k, v in sec["elements"].items() if k and k != "(unknown)"}
        n = len(elements)

        a(f'<details class="L2">')
        a(f'<summary>{tri()} {h(display)} &nbsp;'
          f'<span class="tag">sectionKey: "{h(sk)}"</span>'
          f'<span class="section-count">— {n} info codes</span></summary>')
        a('<div class="children">')
        a(f'<div class="note"><b>title:</b> {h(sec["title"][:80])} &nbsp;|&nbsp; '
          f'<b>heading:</b> {h(sec["heading"])}</div>')

        if sk == "demandAndRefund":
            a('<div class="note">Uses <code>subSections[]</code> — flat structure, no l2/l1 split.</div>')
            for ss in (sec.get("subSections") or []):
                ssk = ss.get("sectionKey", "")
                a(f'<details class="L3">')
                a(f'<summary>{tri()} subSection: <code>{h(ssk)}</code> — {h(ss.get("title",""))}</summary>')
                a('<div class="children">')
                for elem in (ss.get("elements") or []):
                    if not elem: continue
                    cl  = elem.get("columnLabel", [])
                    cdt = elem.get("columnDataType", [])
                    cd  = elem.get("columnData", [])
                    a('<table><tr><th>#</th><th>columnLabel</th><th>dataType</th></tr>')
                    for i, lab in enumerate(cl):
                        dt = cdt[i] if i < len(cdt) else ""
                        a(f'<tr><td>{i}</td><td><code>{h(lab)}</code></td><td>{h(dt)}</td></tr>')
                    a(f'</table><div class="note">{len(cd)} data rows</div>')
                a('</div></details>')  # L3 subsection

        elif not elements:
            a('<div class="note"><i>No active elements observed across scanned files.</i></div>')
        else:
            for ic, e in sorted(elements.items()):
                rc = e["row_counts"]
                cr = f'{min(rc)}–{max(rc)} rows' if min(rc) != max(rc) else f'{rc[0]} row(s)'
                heading = e["description"] or e["category"]

                a(f'<details class="L3">')
                a(f'<summary>{tri()} <span class="badge">{h(ic)}</span>'
                  f' {h(heading)}'
                  f'<span class="l1src-tag">{h(e["l1Src"])}</span></summary>')
                a('<div class="children">')

                # Info fields
                a(f'<div class="field-row"><span class="field-key">Category</span>'
                  f'<span class="field-val">{h(e["category"])}</span></div>')
                a(f'<div class="field-row"><span class="field-key">l1Src</span>'
                  f'<span class="field-val"><code>{h(e["l1Src"])}</code></span></div>')
                a(f'<div class="field-row"><span class="field-key">l1 rows per element</span>'
                  f'<span class="field-val">{cr} (across all scanned files)</span></div>')

                # l2 columns
                if e["l2_labels"]:
                    a('<details class="L4">')
                    a(f'<summary>{tri()} l2 — summary header &nbsp;<span class="tag">1 row per element</span></summary>')
                    a('<div class="children">')
                    a('<table><tr><th>#</th><th>columnLabel</th><th>dataType</th></tr>')
                    for i, lab in enumerate(e["l2_labels"]):
                        dt = e["l2_dt"][i] if i < len(e["l2_dt"]) else ""
                        a(f'<tr><td>{i}</td><td><code>{h(lab)}</code></td><td>{h(dt)}</td></tr>')
                    a('</table>')
                    a('<div class="warn">⚠ columnData[0] may have extra trailing values — zip() against columnLabel</div>')
                    a('</div></details>')  # L4 l2

                # l1 columns
                if e["l1_labels"]:
                    a(f'<details class="L4">')
                    a(f'<summary>{tri()} l1 — transaction detail &nbsp;<span class="tag">{cr}</span></summary>')
                    a('<div class="children">')
                    a('<table><tr><th>#</th><th>columnLabel</th><th>dataType</th></tr>')
                    for i, lab in enumerate(e["l1_labels"]):
                        dt = e["l1_dt"][i] if i < len(e["l1_dt"]) else ""
                        a(f'<tr><td>{i}</td><td><code>{h(lab)}</code></td><td>{h(dt)}</td></tr>')
                    a('</table>')
                    a('<div class="warn">⚠ Each row may have extra trailing values. '
                      'columnDataType length may exceed columnLabel — trim to match.</div>')
                    a('</div></details>')  # L4 l1
                else:
                    a('<div class="note"><i>No l1 transaction columns.</i></div>')

                a('</div></details>')  # L3 element

        a('</div></details>')  # L2 section

    a('</div></details>')  # partB L1

    # ── footer ────────────────────────────────────────────────────────────────
    a('<details class="L1">')
    a(f'<summary>{tri()} footer &nbsp;<span class="tag">object</span></summary>')
    a('<div class="children">')
    footer_notes_map = {"Download ID": "Unique download ID", "IP Address": "Download IP", "Generation Date": "Timestamp"}
    a('<table><tr><th>#</th><th>columnLabel</th><th>Placeholder</th><th>Notes</th></tr>')
    for i, lab in enumerate(schema["footer_labels"], 1):
        placeholder = _FOOTER_PLACEHOLDERS.get(lab, "[redacted]")
        a(f'<tr><td>{i}</td><td><code>{h(lab)}</code></td>'
          f'<td><code>{h(placeholder)}</code></td><td>{footer_notes_map.get(lab,"")}</td></tr>')
    a('</table>')
    a('</div></details>')  # footer

    # ── rejectedFeedbacks ─────────────────────────────────────────────────────
    a('<details class="L1">')
    a(f'<summary>{tri()} rejectedFeedbacks &nbsp;<span class="tag">null | array</span></summary>')
    a('<div class="children">')
    a('<div class="field-row"><span class="field-key">type</span>'
      '<span class="field-val">null or array of feedback objects</span></div>')
    a('<div class="field-row"><span class="field-key">usual value</span>'
      '<span class="field-val">null (assessee has not rejected any source feedback)</span></div>')
    a('</div></details>')

    a('</div></details>')  # Root L0
    a('</div>')  # .tree

    # ── l1Src reference table ─────────────────────────────────────────────────
    a('<hr style="margin:20px 0; border:1px solid #d0e4e8">')
    a('<h2 style="color:#0E6674; margin:0 0 10px">l1Src — Source Type Reference</h2>')
    a('<table><tr><th>l1Src</th><th>Description</th><th>Info Codes</th></tr>')
    src_codes: dict[str, set] = {}
    for sk, sec in schema["sections"].items():
        for ic, e in sec["elements"].items():
            src = e["l1Src"]
            if src not in src_codes:
                src_codes[src] = set()
            if ic:
                src_codes[src].add(ic)
    for src in sorted(src_codes):
        codes = " &nbsp;·&nbsp; ".join(f'<code>{h(c)}</code>' for c in sorted(src_codes[src]))
        desc = h(_L1SRC_DESC.get(src, ""))
        a(f'<tr><td><code>{h(src)}</code></td><td>{desc}</td><td>{codes}</td></tr>')
    a('</table>')

    # ── JS ─────────────────────────────────────────────────────────────────────
    a("""
<script>
function toggleAll(open) {
  document.querySelectorAll('details').forEach(d => { d.open = open; });
}
function toggleLevel(level) {
  // Close all, then open only levels <= requested
  document.querySelectorAll('details').forEach(d => { d.open = false; });
  for (let l = 0; l <= level; l++) {
    document.querySelectorAll('.L' + l).forEach(d => { d.open = true; });
  }
}
</script>
</div></body></html>""")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"HTML tree saved: {out_path}")
# ── Excel generator ────────────────────────────────────────────────────────────

def generate_xlsx(schema: dict, out_path: Path):
    import xlsxwriter

    NAVY    = "#0A1628"; WHITE   = "#FFFFFF"
    DK_GRN  = "#0E6674"; MD_GRN  = "#1a8a9a"
    LT_GRN  = "#e8f5f7"; LT_BLU  = "#e8f0f8"
    GREY_BG = "#f5f5f5"; GREY_TX = "#555555"
    PURPLE  = "#7030A0"

    wb = xlsxwriter.Workbook(str(out_path))

    def _f(**kw):
        p = {"font_name": "Calibri", "font_size": 10, "border": 1,
             "border_color": "#cccccc", "valign": "vcenter", "text_wrap": False}
        p.update(kw)
        return wb.add_format(p)

    F = {
        "brand":  _f(bold=True, color=WHITE, bg_color=NAVY, font_size=11, border=0),
        "hdr":    _f(bold=True, color=WHITE, bg_color=DK_GRN, align="center"),
        "L0":     _f(bold=True, color=WHITE, bg_color=NAVY, font_size=11),
        "L1":     _f(bold=True, color=WHITE, bg_color=DK_GRN),
        "L2sec":  _f(bold=True, color=WHITE, bg_color=MD_GRN),
        "L3node": _f(bold=True, color="#1a3a1a", bg_color=LT_GRN),
        "L3val":  _f(color="#333333", bg_color=LT_GRN),
        "L4node": _f(italic=True, color=GREY_TX, bg_color=GREY_BG),
        "L4src":  _f(italic=True, color=PURPLE,  bg_color=GREY_BG),
        "L4cols": _f(italic=True, color=GREY_TX, bg_color=GREY_BG, text_wrap=True),
        "fld_k":  _f(color="#333333", bg_color=LT_BLU),
        "fld_v":  _f(italic=True, color="#1a1a1a", bg_color=LT_BLU),
        "ref_src": _f(bold=True, color=PURPLE, bg_color="#f5eeff"),
        "ref_cod": _f(color="#1a3a1a", bg_color=LT_GRN),
        "ref_col": _f(italic=True, color="#1a1a1a", bg_color=GREY_BG),
    }

    COLS = ["Node / Field", "Type / l1Src", "Labels / Values / Columns", "Row Count"]

    def row_write(ws, r, indent, node, typ, val="", count="",
                  f0=None, f1=None, f2=None, f3=None, h=15):
        ws.write(r, 0, "    " * indent + node, f0 or F["L3node"])
        ws.write(r, 1, typ,   f1 or F["L3val"])
        ws.write(r, 2, val,   f2 or F["L3val"])
        ws.write(r, 3, count, f3 or F["L3val"])
        ws.set_row(r, h)

    ws1 = wb.add_worksheet("AIS Structure")
    ws1.hide_gridlines(2)
    ws1.freeze_panes(2, 0)
    ws1.set_column(0, 0, 50)
    ws1.set_column(1, 1, 28)
    ws1.set_column(2, 2, 80)
    ws1.set_column(3, 3, 14)

    n_files = schema["file_count"]
    ws1.merge_range(0, 0, 0, 3,
        f"AIS JSON — Complete Structure Reference  ·  {n_files} files scanned  ·  "
        f"No confidential data  ·  AayDoc Capio™", F["brand"])
    ws1.set_row(0, 18)
    for ci, h_label in enumerate(COLS):
        ws1.write(1, ci, h_label, F["hdr"])
    ws1.set_row(1, 15)

    r = 2
    row_write(ws1, r, 0, "AIS JSON Root", "object",
              f"Files scanned: {n_files}",
              f0=F["L0"], f1=F["L0"], f2=F["L0"], f3=F["L0"], h=18)
    r += 1

    # metadata (sanitised)
    row_write(ws1, r, 1, "metadata", "object",
              "  ·  ".join(schema["metadata_keys"]),
              f0=F["fld_k"], f1=F["fld_v"], f2=F["fld_v"], f3=F["fld_v"])
    r += 1

    # header
    row_write(ws1, r, 1, "header", "object",
              "columnLabel: " + "  ·  ".join(schema["header_labels"]),
              f0=F["fld_k"], f1=F["fld_v"], f2=F["fld_v"], f3=F["fld_v"])
    r += 1

    # partA (sanitised)
    row_write(ws1, r, 1, "partA — Assessee Profile", "object", "",
              f0=F["L1"], f1=F["L1"], f2=F["L1"], f3=F["L1"], h=17)
    r += 1
    for lab in schema["partA_labels"]:
        placeholder = _PARTA_PLACEHOLDERS.get(lab, "[value]")
        row_write(ws1, r, 2, lab, "Field", placeholder,
                  f0=F["fld_k"], f1=F["fld_v"], f2=F["fld_v"], f3=F["fld_v"])
        r += 1

    # partB
    total_elems = sum(len(s["elements"]) for s in schema["sections"].values())
    row_write(ws1, r, 1, "partB — Information by Source", "object",
              f"{total_elems} unique element types",
              f0=F["L1"], f1=F["L1"], f2=F["L1"], f3=F["L1"], h=17)
    r += 1

    for sk in SEC_ORDER:
        if sk not in schema["sections"]:
            continue
        sec = schema["sections"][sk]
        display = _SECTION_DISPLAY.get(sk, sk)
        active = {k: v for k, v in sec["elements"].items() if k and k != "(unknown)"}
        row_write(ws1, r, 2, display, sk,
                  sec["title"][:80] if sec["title"] else "",
                  count=f"{len(active)} elements",
                  f0=F["L2sec"], f1=F["L2sec"], f2=F["L2sec"], f3=F["L2sec"], h=16)
        r += 1
        for ic, e in sorted(active.items()):
            rc = e["row_counts"]
            crange = f'{min(rc)}–{max(rc)}' if rc and min(rc) != max(rc) else str(rc[0] if rc else 0)
            heading = e["description"] or e["category"]
            row_write(ws1, r, 3, f"{ic} — {heading}", "Element",
                      e["category"], count=crange + " rows",
                      f0=F["L3node"], f1=F["L3val"], f2=F["L3val"], f3=F["L3val"])
            r += 1
            if e["l2_labels"]:
                row_write(ws1, r, 4, "l2 labels", "",
                          "  ·  ".join(e["l2_labels"]),
                          f0=F["L4node"], f1=F["L4src"], f2=F["L4cols"], f3=F["L4cols"])
                r += 1
            if e["l1_labels"]:
                row_write(ws1, r, 4, "l1 columns", e["l1Src"],
                          "  ·  ".join(e["l1_labels"]),
                          f0=F["L4node"], f1=F["L4src"], f2=F["L4cols"], f3=F["L4cols"])
                r += 1

    # footer (sanitised)
    row_write(ws1, r, 1, "footer", "object",
              "columnLabel: " + "  ·  ".join(schema["footer_labels"]),
              f0=F["fld_k"], f1=F["fld_v"], f2=F["fld_v"], f3=F["fld_v"])
    r += 1
    row_write(ws1, r, 1, "rejectedFeedbacks", "null | array",
              "Feedback rejected by assessee (usually null)",
              f0=F["fld_k"], f1=F["fld_v"], f2=F["fld_v"], f3=F["fld_v"])

    # Sheet 2: l1Src reference
    ws2 = wb.add_worksheet("l1Src Column Reference")
    ws2.hide_gridlines(2)
    ws2.freeze_panes(2, 0)
    ws2.set_column(0, 0, 32)
    ws2.set_column(1, 1, 45)
    ws2.set_column(2, 2, 90)
    ws2.merge_range(0, 0, 0, 2,
        "AIS l1Src Type Reference — All Column Schemas  ·  AayDoc Capio™", F["brand"])
    ws2.set_row(0, 18)
    for ci, h_label in enumerate(["l1Src", "Info Codes Using This Source", "l1 Column Names (in order)"]):
        ws2.write(1, ci, h_label, F["hdr"])
    ws2.set_row(1, 15)

    src_map: dict[str, dict] = {}
    for sk, sec in schema["sections"].items():
        for ic, e in sec["elements"].items():
            src = e["l1Src"]
            if src not in src_map:
                src_map[src] = {"codes": set(), "cols": e["l1_labels"]}
            src_map[src]["codes"].add(ic)
            if len(e["l1_labels"]) > len(src_map[src]["cols"]):
                src_map[src]["cols"] = e["l1_labels"]

    r2 = 2
    for src in sorted(src_map):
        info = src_map[src]
        codes = "  ·  ".join(sorted(c for c in info["codes"] if c))
        cols  = "  ·  ".join(info["cols"]) if info["cols"] else "(no column data)"
        ws2.write(r2, 0, src,   F["ref_src"])
        ws2.write(r2, 1, codes, F["ref_cod"])
        ws2.write(r2, 2, cols,  F["ref_col"])
        ws2.set_row(r2, 28)
        r2 += 1

    wb.close()
    print(f"Excel saved:    {out_path}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("testdata/Decrypted JSON")
    schema = collect_schema(folder)

    doc_dir = Path("Documentation")
    doc_dir.mkdir(exist_ok=True)

    generate_html(schema, doc_dir / "AIS_JSON_Tree.html")
    generate_xlsx(schema, doc_dir / "AIS_JSON_Schema.xlsx")


if __name__ == "__main__":
    main()
