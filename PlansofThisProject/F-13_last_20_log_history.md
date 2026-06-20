# F-13 — Last 20 Run Log History per Client per AY

## Context

CAs need to audit why a download failed across multiple batch runs. Currently the vault stores only the **last** terminal status per client/AY — there is no history. F-13 adds a rolling log store (capped at 20 entries per client per AY) and surfaces it via the "View Log" right-click menu action that is already wired up but greyed out.

GitHub Issue: [#14](https://github.com/dkbholusaria/AayDocCapio/issues/14)

Log lines contain no credentials — no need for encryption. Log history lives in a **separate `log_history.json`** alongside `tax_vault.json` (path via `_app_dir()`). Vault (`vault.py`) is not touched at all.

---

## Files to Create / Modify

| File | Change |
|---|---|
| `ui/log_history.py` | **New file** — `LogStore` manager + `BatchLogCapture` helper + `LogHistoryDialog` |
| `app.py` | Minimal wiring: import, 4 call sites in `_execute_batch`, menu action, `_show_log_history` method |

`vault.py` — **no changes**.

---

## Step 1 — ui/log_history.py (new file)

### 1a. `LogStore` — reads/writes `log_history.json`

```python
import os, json, datetime, threading
from config import _app_dir

class LogStore:
    """
    Plain-JSON store for per-client per-AY run logs.
    File: <_app_dir()>/log_history.json
    Schema: { pan: { ay_label: [ {ts, status, log}, ... ] } }
    Entries are stored oldest-first; capped at 20 per pan/AY.
    """
    MAX_ENTRIES = 20

    def __init__(self):
        self._path = os.path.join(_app_dir(), "log_history.json")
        self._lock = threading.Lock()

    def record(self, pan: str, ay_label: str, status: str, log_text: str):
        with self._lock:
            data = self._load()
            pan = pan.strip().upper()
            entries = data.setdefault(pan, {}).setdefault(ay_label, [])
            entries.append({
                "ts":     datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S"),
                "status": status,
                "log":    log_text,
            })
            if len(entries) > self.MAX_ENTRIES:
                data[pan][ay_label] = entries[-self.MAX_ENTRIES:]
            self._save(data)

    def get(self, pan: str) -> dict:
        """Return {ay_label: [{ts, status, log}, ...]} for a PAN."""
        with self._lock:
            return dict(self._load().get(pan.strip().upper(), {}))

    def _load(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
```

### 1b. `BatchLogCapture` — patches `app.log` during a batch run

```python
class BatchLogCapture:
    """
    Temporarily wraps app.log to buffer per-client log lines.
    Must call start() before the batch loop, start_client(pan) at the
    top of each iteration, flush(pan) when recording, and stop() in finally.
    """
    def __init__(self, app):
        self._app       = app
        self._orig_log  = app.log
        self._buffers: dict[str, list[str]] = {}
        self._current   = None   # active pan

    def start(self):
        _self = self
        def _patched(message):
            _self._orig_log(message)
            if _self._current is not None:
                _self._buffers.setdefault(_self._current, []).append(message)
        self._app.log = _patched

    def start_client(self, pan: str):
        self._current = pan
        self._buffers[pan] = []

    def flush(self, pan: str) -> str:
        return "\n".join(self._buffers.get(pan, []))

    def stop(self):
        self._app.log = self._orig_log
        self._current = None
```

### 1c. `LogHistoryDialog(QDialog)`

Standard PyQt6 dialog following the existing `ui/dialogs.py` pattern.

- Imports: `QDialog`, `QVBoxLayout`, `QHBoxLayout`, `QWidget`, `QTabWidget`, `QTextEdit`, `QLabel`, `QFrame`, `Qt`, `QFont` + `_t()`, `_btn()`, `_lbl()`, `MONO_FONT_NAME as _MONO_FONT` from themes
- Window title: `f"Run History — {name} ({pan})"`
- Size: `700 × 500`, resizable (`setSizeGripEnabled(True)`)
- Layout:
  - Title bar strip (bg: `t.bg_table_alt`) showing name + PAN
  - `QTabWidget` — one tab per AY present in history, **descending sort**
  - Each tab: `QTextEdit` (readonly, `_MONO_FONT` 10pt), entries **newest-first** (reverse stored list)
  - Footer strip with a single "Close" button (`self.accept()`)
- Empty state: centred label "No history yet for this client."

Entry format per run in the text widget:
```
[DD-Mon-YYYY HH:MM:SS]  ✅ 26AS Downloaded
──────────────────────────────────────────────────
<captured log lines>

```
(blank line between entries)

---

## Step 2 — app.py (minimal wiring)

### 2a. Add import near top (with other `ui` imports, line ~35)

```python
from ui.log_history import BatchLogCapture, LogHistoryDialog, LogStore
```

### 2b. Instantiate `LogStore` once on `AayDocCapioApp.__init__`

Add alongside `self.vault = VaultManager(...)`:

```python
self.log_store = LogStore()
```

### 2c. Inside `_execute_batch` — after `_client_out = {}` (~line 2756)

```python
_log_capture = BatchLogCapture(self)
_log_capture.start()
```

### 2d. Inside `for i, target` loop — after extracting `pan` (~line 2797)

```python
_log_capture.start_client(pan)
```

### 2e. Inside `set_status` — after the `record_download` try/except block

```python
        try:
            self.log_store.record(pan, ay_label, text, _log_capture.flush(pan))
        except Exception:
            pass
```

### 2f. In the `finally` block of `_execute_batch`

```python
        finally:
            await browser_manager.close()
            _log_capture.stop()   # F-13: restore app.log
```

### 2g. Enable menu action (~line 1120)

Replace:
```python
            act_log = menu.addAction(_cicon("btn_scan.png"), "View Log")  # F-05 placeholder
            act_log.setEnabled(False)
```
With:
```python
            act_log = menu.addAction(_cicon("btn_scan.png"), "View Log")
            act_log.triggered.connect(lambda checked=False, _a=a: self._show_log_history(_a))
```

### 2h. Add `_show_log_history` method (near `_open_mail_docs`, ~line 2005)

```python
def _show_log_history(self, a: dict):
    history = self.log_store.get(a.get("pan", ""))
    LogHistoryDialog(self, name=a.get("name", ""), pan=a.get("pan", ""), history=history).exec()
```

---

## Sequence

1. Create `ui/log_history.py` with `LogStore`, `BatchLogCapture`, `LogHistoryDialog`
2. `app.py` — import (2a), `self.log_store` init (2b), 4 call sites in `_execute_batch` (2c–2f), menu action (2g), `_show_log_history` (2h)

---

## Verification

1. `.venv/bin/python app.py`
2. Run a batch download for 1–2 clients
3. Right-click a client → "View Log" → dialog opens with AY tab and timestamped log entries
4. Run again for the same client → second entry appears at top of the same tab
5. `log_history.json` exists in project root (dev mode) with correct structure — no credentials, no encryption
6. `tax_vault.json` unchanged in structure; main grid status display unaffected
