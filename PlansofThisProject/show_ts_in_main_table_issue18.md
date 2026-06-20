# Plan: Show Last Download Timestamp in Main Client Table

**GitHub Issue:** #18
**Label:** enhancement / P2

## Context

The `ts` field is stored in `tax_vault.json` for every download attempt via `vault.record_download()`, but is never surfaced in the UI. The main client table shows `Last Download Status` and `Last Saved Location` but the user has no way to see *when* that status was recorded without manually opening the vault file. Adding a timestamp column makes it immediately clear whether a status is fresh or stale.

---

## Changes Required

### 1. Add column constant — `app.py` lines 824–831

Insert `_TC_TS` between `_TC_STATUS` and `_TC_PATH`, shifting `_TC_PATH` and `_TC_ACTS` up by one:

```python
_TC_CHK    = 0
_TC_NAME   = 1
_TC_PAN    = 2
_TC_DOB    = 3
_TC_STATUS = 4
_TC_TS     = 5   # NEW
_TC_PATH   = 6   # was 5
_TC_ACTS   = 7   # was 6
```

### 2. Widen the table to 8 columns — `app.py` line 834

```python
self.client_table = QTableWidget(0, 8)   # was 7
```

### 3. Add column header — `app.py` lines 835–838

```python
self.client_table.setHorizontalHeaderLabels([
    "", "Name  ⇅", "PAN  ⇅", "Date of Birth",
    "Last Download Status", "Last Download Time", "Last Saved Location", ""
])
```

### 4. Set column width + resize mode — `app.py` lines 877–890

Add after `_TC_STATUS` width:
```python
self.client_table.setColumnWidth(self._TC_TS, 155)
```
Add resize mode (Interactive):
```python
header.setSectionResizeMode(self._TC_TS, QHeaderView.ResizeMode.Interactive)
```

### 5. Populate `_TC_TS` cell in the row-build loop — `app.py` after line 1348

Insert after the status cell block:
```python
# Col 5: Last Download Time
ts_text = hist.get("ts", "")
ts_item = QTableWidgetItem(ts_text if ts_text else "—")
ts_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
ts_item.setForeground(QColor("#64748B"))
self.client_table.setItem(i, self._TC_TS, ts_item)
```

---

## Files to Modify

- `app.py` — the only file; all changes are in the column constant block, `_mk_client_table`, and the row-population loop

---

## Verification

1. Run `python app.py`
2. Select an AY that has download history — confirm a "Last Download Time" column appears showing timestamps like `13-Jun-2026 17:07:06`
3. For clients with no history the cell should show `—`
4. Column is resizable; sorting not required (timestamps are read-only display)
