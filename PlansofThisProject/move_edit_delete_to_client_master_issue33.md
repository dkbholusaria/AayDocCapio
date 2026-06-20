# Plan: Move Edit / Delete Actions to Client Master Menu

**GitHub Issue:** #33
**Label:** enhancement / P2

## Context

The main table control bar has a "Delete Selected" danger button that risks accidental deletion.
The `• • •` per-row dots menu has Edit Client and Delete Client — these stay for quick row-level access
but the user also wants these operations available centrally in Client Master for a cleaner main screen.

### Goals
1. Remove "Delete Selected" from the control bar — cleaner main screen, reduces accidental deletion risk
2. Add "Edit Client…" and "Delete Client(s)…" to Client Master menu as the authoritative central location
3. Keep `• • •` dots menu intact (Edit + Delete stay there for quick access)
4. Add greyed "View Log" placeholder to dots menu for F-05

---

## Target State

### Client Master menu (after)
```
Client Master
├── Add New Client
├── ─────────────
├── Edit Client…           ← NEW — always enabled; opens client picker (single-select)
├── Delete Client(s)…      ← NEW — always enabled; opens client picker (multi-select)
├── ─────────────
├── Import from CSV / Excel
├── Export Client Data
├── ─────────────
└── Download Import Template
```

### `• • •` dots menu (after)
```
• • •  (per row — unchanged except View Log added)
├── Edit Client            ← kept as-is
├── ─────────────
├── Delete Client          ← kept as-is
├── ─────────────
└── View Log               ← NEW placeholder for F-05 (greyed / disabled)
```

### Control bar (after)
```
[Run in background checkbox]   [Email Docs]   [Download ▾]   [Exit]
   ↑ Delete Selected removed — no longer here
```

---

## Client-Picker Popup (`_ClientPickerDialog`)

A reusable `QDialog` parameterised by `mode`:

| mode | Title | Selection rule | OK label |
|---|---|---|---|
| `"edit"` | "Select Client to Edit" | Single — checking one auto-unchecks all others | "Edit" |
| `"delete"` | "Select Client(s) to Delete" | Multi — any number | "Delete" |

### Layout
- Search box (filter by name or PAN)
- Scrollable list — each row: `[checkbox]  Name  —  PAN`
- Footer: **Cancel** | **OK** (OK disabled until valid selection: ≥1 for delete, exactly 1 for edit)

### Return
- `.exec()` → `Accepted` or `Rejected`
- `.selected_ids` → list of assessee IDs

---

## Changes Required

### 1. New `_ClientPickerDialog` class — add before `MainWindow`

Full reusable dialog with:
- `__init__(parent, clients, mode)` — builds layout
- `_on_search(text)` — show/hide rows
- `_on_check_changed()` — for edit mode, enforce single-select; enable/disable OK
- `selected_ids` property

### 2. Add actions to Client Master menu — `_build_ui()` (~line 162)

```python
act_edit_cl = QAction(_micon("icon_edit.png"),   "Edit Client…",      self)
act_del_cl  = QAction(_micon("icon_delete.png"), "Delete Client(s)…", self)
act_edit_cl.triggered.connect(self._pick_and_edit_client)
act_del_cl.triggered.connect(self._pick_and_delete_clients)
self._act_edit_cl = act_edit_cl
self._act_del_cl  = act_del_cl

cm_menu.addAction(act_add)
cm_menu.addSeparator()
cm_menu.addAction(act_edit_cl)
cm_menu.addAction(act_del_cl)
cm_menu.addSeparator()
cm_menu.addAction(act_imp)
cm_menu.addAction(act_exp)
cm_menu.addSeparator()
cm_menu.addAction(act_tpl)
```

### 3. Add two handler methods — near `_open_edit_client`

```python
def _pick_and_edit_client(self):
    clients = [{"id": a["id"], "name": a["name"], "pan": a["pan"]}
               for a in self.vault.get_all_assessees()]
    dlg = _ClientPickerDialog(self, clients, mode="edit")
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_ids:
        a_id = dlg.selected_ids[0]
        for row in range(self.client_table.rowCount()):
            item = self.client_table.item(row, self._TC_NAME)
            if item and item.data(Qt.ItemDataRole.UserRole) == a_id:
                acts_item = self.client_table.item(row, self._TC_ACTS)
                if acts_item:
                    a = acts_item.data(Qt.ItemDataRole.UserRole + 1)
                    if a:
                        self._open_edit_client(a)
                break

def _pick_and_delete_clients(self):
    clients = [{"id": a["id"], "name": a["name"], "pan": a["pan"]}
               for a in self.vault.get_all_assessees()]
    dlg = _ClientPickerDialog(self, clients, mode="delete")
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_ids:
        ids  = dlg.selected_ids
        all_ = self.vault.get_all_assessees()
        names = [a["name"] for a in all_ if a["id"] in ids]
        msg = f"Permanently delete {len(ids)} client(s)?\n\n" + "\n".join(f"• {n}" for n in names)
        if QMessageBox.question(self, "Confirm Delete", msg,
               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
           ) == QMessageBox.StandardButton.Yes:
            for a_id in ids:
                self.vault.delete_assessee(a_id)
                self.selected_ids.discard(a_id)
            self.refresh_grid()
            self._update_selection_label()
```

### 4. Update `• • •` dots menu — `_on_cell_clicked()` (~line 931)

Keep Edit Client and Delete Client. Add View Log placeholder after a separator:

```python
menu.addAction(_cicon("icon_edit.png"),   "Edit Client",   lambda av=a:     self._open_edit_client(av))
menu.addSeparator()
menu.addAction(_cicon("icon_delete.png"), "Delete Client", lambda id_=a_id: self.delete_assessee(id_))
menu.addSeparator()                                          # ← NEW
act_log = menu.addAction(_cicon("btn_scan.png"), "View Log")  # ← NEW F-05 placeholder
act_log.setEnabled(False)                                    # ← NEW
```

### 5. Remove "Delete Selected" from control bar — `_mk_control_bar()` (~line 1030)

Delete these lines:
```python
self.btn_delete_sel = _btn("Delete Selected", "danger", height=34, min_width=130, icon="btn_delete.png")
self.btn_delete_sel.setEnabled(False)
self.btn_delete_sel.clicked.connect(self.delete_selected)
hl.addWidget(self.btn_delete_sel)
hl.addSpacing(8)
```

### 6. Remove `btn_delete_sel` enable/disable — `_update_selection_label()` (~line 1455)

Delete:
```python
if hasattr(self, "btn_delete_sel"):
    self.btn_delete_sel.setEnabled(len(self.selected_ids) > 0)
```

### 7. Update `_lock_ui()` (~line 2076)

```python
# Before:
widgets = [self.ay_combo, self.btn_delete_sel, self.btn_run, self.chk_headless]

# After:
widgets = [self.ay_combo, self.btn_run, self.chk_headless]
```

Lock/unlock new menu actions during batch:
```python
for act in (getattr(self, "_act_edit_cl", None), getattr(self, "_act_del_cl", None)):
    if act:
        act.setEnabled(not lock)
```

---

## Files to Modify

- `app.py` only — new `_ClientPickerDialog` class, `_build_ui`, `_mk_control_bar`,
  `_on_cell_clicked`, `_update_selection_label`, `_lock_ui`, two new handler methods.

## What Does NOT Change

- `_TC_ACTS` column, column count (8), widths — unchanged
- `dots_item` row-build loop — unchanged
- `delete_assessee()`, `delete_selected()`, `_open_edit_client()` — unchanged

---

## Verification

1. Run `python app.py`
2. Control bar has no "Delete Selected" button — layout is clean
3. `• • •` per row → Edit Client, Delete Client (both work as before) + greyed View Log
4. Client Master → "Edit Client…" → picker opens with search + single-select list → Edit opens pre-filled dialog
5. Client Master → "Delete Client(s)…" → picker opens with search + multi-select list → named confirmation → deletes
6. During batch run → Edit Client… and Delete Client(s)… are disabled in Client Master
