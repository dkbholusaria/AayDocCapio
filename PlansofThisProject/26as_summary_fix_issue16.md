# Plan: Fix 26AS Summary Sheet — Correct Deductor Matching + Link All Rows
**GitHub Issue:** [#16](https://github.com/dkbholusaria/AayDocCapio/issues/16)

## Context

Two related problems in the 26AS summary sheet:

1. **Wrong match bug** — amounts are looked up using name only. Two deductors with the same name but different TANs/PANs (e.g. two branches of the same bank) cause the summary to show the wrong amounts for the second deductor.

2. **Audit trail** — currently only the deductor name cell (column 2) is a clickable link. The TAN/PAN column and all other data cells have no link. For a full audit trail, every summary row should have at minimum the TAN/PAN cell also linked to the source detail sheet.

Both problems share the same two call sites in `automation/as26_converter.py`.

## Root Cause — Bug 1 (name-only match)

| Location | Lines |
|---|---|
| `_html_summary()` | 779–781 |
| `_write_xlsx()` | 1615–1618 |

Both use a name-only filter against `pdata["rows"]`. `row_ids[roman][sr]` already holds `{"name": name, "tan": tan, "xl_row": ...}` — `tan` is available but ignored.

## Fix

### Part A — Correct match helper (add once, near start of `_html_summary` and reuse in `_write_xlsx`)

```python
def _match_ded(rows, name, tan):
    name_fields = ("Name of Deductor","Name of Collector","Name of Buyer","Name of Deductee")
    tan_fields  = ("TAN of Deductor","TAN of Collector","PAN of Deductee",
                   "PAN of Buyer","PAN of Seller","PAN of Deductor")
    def _n(d): return (next((d.get(f) for f in name_fields if d.get(f)), "") or "").strip()
    def _t(d): return (next((d.get(f) for f in tan_fields  if d.get(f)), "") or "").strip()
    tan = (tan or "").strip(); name = (name or "").strip()
    if tan:
        hit = [d for d in rows if _n(d) == name and _t(d) == tan]
        if hit:
            return hit
    return [d for d in rows if _n(d) == name]
```

Replace both name-only list comprehensions with `_match_ded(pdata["rows"], name, tan)`.

### Part B — Link TAN/PAN column in Excel summary (audit trail)

Currently `ws_sum.write(r, 3, tan, sf)` writes TAN/PAN as plain text.  
Change it to `ws_sum.write_url(r, 3, f"internal:'{sheet_name}'!A{xl_row}", F_LINK, tan)`.

This gives auditors two clickable entry points per row (name + TAN/PAN) both pointing to the same detail sheet row.

### Part C — Link TAN/PAN column in HTML summary (audit trail)

Currently `<td>{tan}</td>` is plain text.  
Change it to `<td class="link"><a onclick="{onclick}">{tan}</a></td>` (reusing the same `onclick` already built for the name cell).

## Files to Modify

`automation/as26_converter.py` — three targeted changes:
- Lines 779–781: replace name-only match with `_match_ded()`
- Lines 822–823: add link class to TAN cell in HTML
- Lines 1615–1618: replace name-only match with `_match_ded()`
- Line 1644: change `ws_sum.write` to `ws_sum.write_url` for TAN column

## Verification

1. Run converter on a 26AS with two deductors sharing the same name but different TANs.
2. Excel: confirm both rows show correct (distinct) amounts, and both Name and TAN cells are clickable links jumping to the correct detail row.
3. HTML: confirm TAN cell is also clickable and navigates to the correct section.
4. Run on a normal 26AS (no duplicate names) and confirm no regressions.
