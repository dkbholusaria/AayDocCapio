# B-07: AIS Excel — 4 Data Extraction Bugs — Implementation Plan

**GitHub Issue:** #19 (pending — gh issue create command still running)
**File:** `automation/ais_converter.py`
**Priority:** P1 / Bug

---

## Diagnostic Findings (from grep of decrypted JSONs)

Ran `grep -o '"name": "..."'` across both AFCPB9287R (Vikas Banga) and ABPPD4671C
(Shivasis Das) decrypted JSONs. Key confirmed column names:

| Column name in JSON        | Code lookup        | Match? |
|----------------------------|--------------------|--------|
| `Amount Paid/Credited`     | `_c("Amount Paid/Credited")`  | ✓ OK   |
| `TDS Deducted`             | `_c("TDS Deducted")`          | ✓ OK   |
| `TCS Deposited`            | `_c("TDS Deposited")`         | ✗ MISMATCH — Bug b |
| `Quarter`                  | superset col name             | ✓ Name OK — data may be null |
| `Total Purchase Amount`    | `_SFT_18PUR_NUM` / superset   | ✓ Column exists in JSON |
| `Total Sales Value`        | `_SFT_18PUR_NUM` / superset   | ✓ Column exists in JSON |
| `Market Purchase`          | `_SFT_17PUR_NUM` / superset   | ✓ OK   |

---

## Revised Root-Cause Analysis

### Bug a — SFT-18(Pur) rows missing from Excel

**Root cause:** `_write_sft_sheet` (line ~836) and `_write_sft_flat_summary` (line ~740)
both have this guard:
```python
l2 = _get_l2(elem)
if not l2:
    continue   ← empty dict is falsy → entire element silently skipped
```
`_get_l2` returns `{}` when `l2.columnData` is empty/absent for an element.
The l1 data (the actual rows) exists in the JSON — confirmed by the presence of
`"Total Purchase Amount"` and `"Total Sales Value"` column names.

**Fix:** Remove `if not l2: continue`. Guard only on `if not l1_rows`. Derive `source`
from element-level fallback when l2 is empty.

---

### Bug b — TCS (206CQ) TDS/TCS Deposited column blank

**Root cause confirmed:** `_std_row` (line ~533) hard-codes `"TDS Deposited"` for col 10.
TCS entries in the JSON use `"TCS Deposited"` as the column name.
`_c("TDS Deposited")` fails silently → returns `""` → `_parse_amount("")` → `None` → `0`.

Note: Cols 8 (`"Amount Paid/Credited"`) and 9 (`"TDS Deducted"`) match correctly for TCS.
Only col 10 is affected.

**Fix:** Add `"TCS Deposited"` as a fallback alias for col 10 lookup.

---

### Bug c — Section 194J TDS values blank

**Root cause (revised):** Column names `"Amount Paid/Credited"` and `"TDS Deducted"`
exist in the JSON and match the code — so the column lookup itself is NOT the issue.
Most likely root cause: the same `if not l2: continue` guard in `_write_tds_sheet`
(line ~461) is skipping certain 194J elements when their `l2.columnData` is empty.

This is the **same class of bug as Bug a**, just in the TDS sheet writer, not the SFT writer.

**Fix:** Same guard removal pattern in `_write_tds_sheet`.

---

### Bug d — Quarter blank on some SFT-17(Pur) rows

**Root cause (revised):** `"Quarter"` IS the correct column name in the JSON —
confirmed by grep. The blank values are likely:
- The Quarter field is genuinely null/empty in the source AIS data for those rows
  (some transactions may not have a quarter assigned by the depository), OR
- Some SFT-17(Pur) elements have a different column order causing `_map_to_superset`
  to put data in the wrong slot

The `_SFT_17PUR_RENAME` alias fix from the original plan is **not needed**.

**What to check before fixing:** Look at the actual l1 row data for SFT-17(Pur)
elements where Quarter appears blank in Excel — confirm whether the JSON value is
literally null/empty, or if there's a column ordering issue.

**Likely fix:** If data is truly null, no code fix is needed (it's a source data issue).
If it's a column ordering issue, the fix is in `_map_to_superset` / the superset
definition for SFT-17(Pur).

---

## Code Changes — Finalized

### Change 1 — Fix guard in `_write_sft_sheet` (Bug a)

**Location:** `_write_sft_sheet`, lines ~836–845

```python
# BEFORE
for elem in elems:
    l2 = _get_l2(elem)
    if not l2:
        continue
    l1_cols, l1_rows = _get_l1(elem)
    l1_rows = _active_rows(l1_cols, l1_rows)
    if not l1_rows:
        continue
    source = l2.get("source", "")

# AFTER
for elem in elems:
    l2 = _get_l2(elem)
    l1_cols, l1_rows = _get_l1(elem)
    l1_rows = _active_rows(l1_cols, l1_rows)
    if not l1_rows:
        continue
    source = l2.get("source", "") if l2 else (elem.get("source", "") or "")
```

Apply same change in `_write_sft_flat_summary` (~line 740–748).

---

### Change 2 — Fix guard in `_write_tds_sheet` (Bug c)

**Location:** `_write_tds_sheet`, lines ~461–468

```python
# BEFORE
for elem in elems:
    l2 = _get_l2(elem)
    if not l2:
        continue
    l1_cols, l1_rows = _get_l1(elem)
    l1_rows = _active_rows(l1_cols, l1_rows)
    if not l1_rows:
        continue
    name, tan = _split_source(l2.get("source", ""))

# AFTER
for elem in elems:
    l2 = _get_l2(elem)
    l1_cols, l1_rows = _get_l1(elem)
    l1_rows = _active_rows(l1_cols, l1_rows)
    if not l1_rows:
        continue
    raw_src = l2.get("source", "") if l2 else (elem.get("source", "") or "")
    name, tan = _split_source(raw_src)
```

---

### Change 3 — Fix TCS Deposited alias in `_std_row` (Bug b)

**Location:** `_std_row`, lines ~533–535

```python
# BEFORE
for ci, col in [(8, "Amount Paid/Credited"), (9, "TDS Deducted"), (10, "TDS Deposited")]:
    amt = _parse_amount(str(_c(col)))
    ws.write_number(row, ci, amt if amt is not None else 0, F_NUM)

# AFTER
for ci, col, fallbacks in [
    (8,  "Amount Paid/Credited", []),
    (9,  "TDS Deducted",        []),
    (10, "TDS Deposited",       ["TCS Deposited"]),
]:
    val = _c(col)
    if val == "" and fallbacks:
        for fb in fallbacks:
            val = _c(fb)
            if val != "":
                break
    amt = _parse_amount(str(val))
    ws.write_number(row, ci, amt if amt is not None else 0, F_NUM)
```

---

### Change 4 — Bug d (Quarter)

Investigate before coding. No rename fix needed (column name confirmed correct).
Check if the data value itself is null in JSON for those rows.
If it is a data issue from the source, document it as known limitation (data comes
blank from ITD portal for some SFT-17 transactions).

---

## Implementation Order

1. Apply **Change 1** — `_write_sft_sheet` guard removal (Bug a)
2. Apply **Change 1** same pattern in `_write_sft_flat_summary` (Bug a)
3. Apply **Change 2** — `_write_tds_sheet` guard removal (Bug c)
4. Apply **Change 3** — TCS Deposited alias in `_std_row` (Bug b)
5. Investigate Bug d — grep/inspect actual SFT-17(Pur) l1 row data for null Quarter
6. Regenerate Excel for both clients and verify
7. Update `Documentation/ISSUES_BACKLOG.md`
8. Close GitHub issue #19

---

## Files Changed

| File | Change |
|------|--------|
| `automation/ais_converter.py` | Changes 1, 2, 3 (and 4 if needed) |
| `Documentation/ISSUES_BACKLOG.md` | Add B-07 entry |

---

## Verification Checklist

- [ ] SFT-18(Pur) sheet shows rows for Vikas Banga
- [ ] SFT-18(Pur) sheet shows rows for Shivasis Das
- [ ] TCS-206CQ rows in Part B1: TDS/TCS Deposited column non-zero
- [ ] 194J rows in Part B1: all amount columns populated
- [ ] SFT-17(Pur): confirm Quarter blank is a source-data issue (not a code bug)
- [ ] No regression on other sheets (SFT-17-LES(M), SFT-015, SFT-016*, etc.)
