# F-121 Return Status — Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Finish GitHub issue #121 — make the Income Tax ▸ Return Status tab fully usable: decompose the status, add the missing "audit report filed/not filed" filter, confirm the audit check against the portal, populate rich fields from the Downloads flow, retire the legacy dialog, and cover it with tests.

**Architecture:** The feature already exists on `main` (commit `dd34938`): an inline `ReturnStatusTab` (`ui/dialogs.py`) backed by `automation/return_status.py` (`check_return_status`, `scan_full_status`) and the vault (`return_status_history`, `audit_applicable`). This plan fills the documented gaps in place — no new subsystem. Work happens on branch `fix/121-return-status-complete` in an isolated worktree.

**Tech Stack:** Python 3.12, PyQt6, Playwright (async), pytest (`pytest-asyncio` for async probes), the app's encrypted `VaultManager`.

**Decisions locked with the user:**
- Do **not** add the portal "Export to Excel" data source; keep populating from the existing card scan (`scan_full_status`). (Item dropped from scope.)
- Audit-report-filed check must **hit the portal** (Income Tax Forms → View Filed Forms card listing), with the existing local-disk scan (`has_audit_report`) kept only as a fallback when the portal probe is unavailable.
- Add **full** test coverage including an offscreen GUI smoke test.

**Test command (no venv inside worktree):**
```
/home/faheem/Documents/AayDocCapio/.venv/bin/python -m pytest tests/test_return_status.py -q
```

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `requirements.txt` | declare test deps | add `pytest`, `pytest-asyncio` under a tests section |
| `tests/__init__.py` | make `tests` a package | create (empty) |
| `tests/conftest.py` | force `QT_QPA_PLATFORM=offscreen`, add `qapp` fixture, `gui` marker | create |
| `tests/test_return_status.py` | all F-121 tests (pure helpers, fake-page probe, vault round-trip, GUI smoke) | create |
| `automation/return_status.py` | status decomposition + refund/everify + portal audit probe | modify |
| `vault.py` | persist `everify_pending`; docstring fix | modify |
| `automation/downloader_filed_returns.py` | record full status (not just 4 fields) on download | modify |
| `automation/batch_handlers.py` | pass full status through `return_statuses` | modify |
| `app.py` | persist full status from Downloads; implement `start_audit_probe`; retire legacy menu dialog | modify |
| `ui/dialogs.py` | add decomposition status text, `_COL_EVERIFY`, audit-report filed/not-filed filters; default audit probe | modify |

---

## Task 1: Test scaffolding

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `requirements.txt`

- [x] **Step 1: Add test deps**

Append under the runtime deps block in `requirements.txt`:

```
# ── Test dependencies (dev only) ──────────────────────────────────────────────
pytest>=8.0
pytest-asyncio>=0.23
```

- [x] **Step 2: Create `tests/__init__.py`** (empty file).

- [x] **Step 3: Create `tests/conftest.py`**

```python
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "gui: test builds or drives Qt widgets (offscreen)")

@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
```

- [x] **Step 4: Confirm existing suites still import**

Run: `/home/faheem/Documents/AayDocCapio/.venv/bin/python -m pytest test_filed_forms.py test_f14_skip.py -q`
Expected: all pass (17 passed).

- [x] **Step 5: Commit**

```
git add requirements.txt tests/__init__.py tests/conftest.py
git commit -m "test: add tests/ package with offscreen Qt fixture (#121)"
```

---

## Task 2: Status decomposition helpers (pure functions)

**Files:**
- Test: `tests/test_return_status.py`
- Modify: `automation/return_status.py`

- [x] **Step 1: Write failing tests** — create `tests/test_return_status.py` with the refund/decomposition section (see final test file, lines for `_derive_refund_status`, `compute_everify_pending`, `_is_everify_pending`, `_extract_section`).

- [x] **Step 2: Run, expect failure**

Run: `.../python -m pytest tests/test_return_status.py -q -k "refund or everify or section"`
Expected: FAIL with `ImportError` / `AttributeError` for `compute_everify_pending`, `_is_everify_pending`.

- [x] **Step 3: Implement in `automation/return_status.py`**

Add after `_derive_refund_status`:

```python
_VERIFIED_RE = re.compile(r"e-?\s*verif", re.IGNORECASE)
_PROCESSED_RE = re.compile(r"process", re.IGNORECASE)


def _is_everify_pending(status_text) -> bool:
    """Heuristic on a raw portal status string: True if the filing looks like
    it still awaits e-verification. Never raises on junk input."""
    text = str(status_text or "")
    return bool(re.search(r"pending for e-?\s*verif", text, re.IGNORECASE))


def compute_everify_pending(filed, e_verified, status_text="") -> bool:
    """Whether the latest filing is filed-but-not-yet-e-verified.

    An explicit e_verified flag wins: True => not pending, False => pending.
    When the flag is unknown (None) and the return is filed, fall back to the
    status text: a verified/processed status means not pending, anything else
    (including a bare "ITR Filed") means still pending."""
    if not filed:
        return False
    if e_verified is True:
        return False
    if e_verified is False:
        return True
    text = str(status_text or "")
    if _VERIFIED_RE.search(text) or _PROCESSED_RE.search(text):
        return False
    return True
```

- [x] **Step 4: Run, expect pass**

Run: `.../python -m pytest tests/test_return_status.py -q -k "refund or everify or section"`
Expected: PASS.

- [x] **Step 5: Commit**

```
git add automation/return_status.py tests/test_return_status.py
git commit -m "feat(return-status): decompose e-verification pending state (#121)"
```

---

## Task 3: Audit-report portal probe + local fallback

**Files:**
- Test: `tests/test_return_status.py`
- Modify: `automation/return_status.py`

- [x] **Step 1: Write failing tests** — the `_FakeCard`/`_FakeLocator`/`_FakePage` helpers plus `test_probe_audit_report_*` and existing `test_has_audit_report_*` tests.

- [x] **Step 2: Run, expect failure**

Run: `.../python -m pytest tests/test_return_status.py -q -k "audit_report"`
Expected: FAIL — `has_audit_report` present (import ok) but `probe_audit_report` missing → ImportError.

- [x] **Step 3: Implement** at the end of `automation/return_status.py`

```python
_AUDIT_CATEGORY_RE = re.compile(r"3c[ab]\s*-\s*3cd", re.IGNORECASE)


async def probe_audit_report(page, step) -> bool:
    """Whether the portal lists an audit-report form (Form 3CB-3CD or
    3CA-3CD) under Income Tax Forms for this already-logged-in client.

    ``page`` must already be on the Income Tax Forms category-listing screen
    (navigate_to_filed_forms()). Reads every visible ``.eachMatCardStyle``
    card text and looks for a "3CB-3CD"/"3CA-3CD" form code — the same card
    markup downloader_filed_forms._read_category_cards() uses. Returns True
    if an audit-report category is present, False otherwise. Raises only on
    page-level failure so the caller can fall back to has_audit_report()."""
    cards = await page.evaluate("""() => {
        const visible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        };
        return [...document.querySelectorAll('.eachMatCardStyle')]
            .filter(visible)
            .map(el => (el.innerText || '').replace(/\\s+/g, ' ').trim())
            .filter(Boolean);
    }""")
    for text in cards or []:
        if _AUDIT_CATEGORY_RE.search(text):
            step(f"Audit report form present on portal: {text[:80]}")
            return True
    step(f"No audit-report (3CB-3CD/3CA-3CD) category found ({len(cards or [])} cards)")
    return False
```

- [x] **Step 4: Run, expect pass** — `-k "audit_report"` → PASS.

- [x] **Step 5: Commit**

```
git add automation/return_status.py tests/test_return_status.py
git commit -m "feat(return-status): probe portal for filed audit report (#121)"
```

---

## Task 4: Persist `everify_pending` in the vault + Downloads flow (kill two birds)

**Files:**
- Test: `tests/test_return_status.py`
- Modify: `vault.py:544` (`record_return_status`)
- Modify: `automation/return_status.py` (compute + return `everify_pending`)
- Modify: `automation/downloader_filed_returns.py:843-872`
- Modify: `automation/batch_handlers.py:236-279`
- Modify: `app.py:7645-7653` and `app.py:7765-7773`

- [x] **Step 1: Write failing test** — `test_vault_return_status_roundtrip_persists_rich_fields` (uses `VaultManager(path)` with a temp json file; asserts `everify_pending` round-trips).

- [x] **Step 2: Run, expect failure**

Run: `.../python -m pytest tests/test_return_status.py -q -k "roundtrip"`
Expected: FAIL — `everify_pending` not stored.

- [x] **Step 3: `vault.py`** — add `everify_pending=None` param to `record_return_status` and store it:

```python
    def record_return_status(self, pan, ay_label, status, status_date="", filing_date="",
                             ack_no="", filed=None, section="", revised=None,
                             revised_section="", rectified=None, e_verified=None,
                             processed=None, refund_status="", everify_pending=None):
        ...
            "refund_status": refund_status,
            "everify_pending": everify_pending,
            "ts": datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S"),
```

Also update the `get_return_status` docstring to list the rich fields.

- [x] **Step 4: `scan_full_status`** — add `everify_pending` to `empty` and the success dict:

```python
        everify = compute_everify_pending(True, e_verified, status_text)
        ...
        "everify_pending": everify,
```

- [x] **Step 5: Downloads flow uses full scan** — in `automation/downloader_filed_returns.py` replace `scan_latest_status` import/use with `scan_full_status` (same call signature) and keep `empty_status` as the `scan_full_status` empty dict (or just `{}` with `.get` guards; callers use `.get`).

- [x] **Step 6: `app.py` Downloads persistence** — in both `record_return_status` blocks, forward every field:

```python
self.vault.record_return_status(
    pan, _ay_value, _status_info.get("status", ""),
    status_date=_status_info.get("status_date", ""),
    filing_date=_status_info.get("filing_date", ""),
    ack_no=_status_info.get("ack_no", ""),
    filed=_status_info.get("filed"), section=_status_info.get("section", ""),
    revised=_status_info.get("revised"), revised_section=_status_info.get("revised_section", ""),
    rectified=_status_info.get("rectified"), e_verified=_status_info.get("e_verified"),
    processed=_status_info.get("processed"), refund_status=_status_info.get("refund_status", ""),
    everify_pending=_status_info.get("everify_pending"))
```

- [x] **Step 7: Run tests** — `-k "roundtrip"` PASS; then full file.

- [x] **Step 8: Commit**

```
git add vault.py automation/return_status.py automation/downloader_filed_returns.py automation/batch_handlers.py app.py tests/test_return_status.py
git commit -m "feat(return-status): persist full status from Downloads flow (#121)"
```

---

## Task 5: UI — decomposed status column, audit filters

**Files:**
- Test: `tests/test_return_status.py`
- Modify: `ui/dialogs.py` (`ReturnStatusTab`)

- [x] **Step 1: Write failing tests** — `test_tab_lists_only_income_tax_clients`, `test_tab_columns_render_decomposed_status`, `test_tab_pending_everify_filter`, `test_tab_audit_report_filter`.

- [x] **Step 2: Run, expect failure**

Run: `.../python -m pytest tests/test_return_status.py -q -k "tab_"`
Expected: FAIL — `_COL_EVERIFY`, `_chk_audit_report_filed`, `_chk_audit_report_not_filed`, `_audit_report_by_pan` missing.

- [x] **Step 3: `ui/dialogs.py` changes**

- Add `_COL_EVERIFY = 10` right after `_COL_STATUS`, then `_COL_REFUND = 11`, `_COL_AUDIT = 12`, `_COL_AUDIT_REPORT = 13`; insert `"e-Verify"` into `_HEADERS` after `"Last Status"`.
- Add two checkboxes to the filter row: `self._chk_audit_report_filed = QCheckBox("Audit report filed")`, `self._chk_audit_report_not_filed = QCheckBox("Audit report not filed")`; both `stateChanged → self._refresh_table`.
- Add `self._audit_report_by_pan: dict = {}` and `self._audit_probe = audit_probe` in `__init__`.
- In `_client_rows`: set `audit_report = self._audit_report_by_pan.get(pan, "<missing>")`; if `"<missing>"`, fall back to local `has_audit_report(root, pan, ay)` when `audit_on and root`, else `None`. Add `"everify_pending": entry.get("everify_pending")` to the row dict.
- In `_passes_filters`, add:

```python
if self._chk_audit_report_filed.isChecked() and r["audit_report"] is not True:
    return False
if self._chk_audit_report_not_filed.isChecked() and r["audit_report"] is not False:
    return False
```

- In `_refresh_table`: render `_COL_STATUS` as `f"{status} ({date})"`; render `_COL_EVERIFY` from `compute_everify_pending(...)`:

```python
everify = r["everify_pending"]
if everify is None:
    everify = compute_everify_pending(r["filed"], r["e_verified"], r["status"])
if not r["filed"]:
    _set(self._COL_EVERIFY, "—", muted=True)
else:
    _set(self._COL_EVERIFY, "Pending" if everify else "Done",
         warn=bool(everify), muted=not everify)
```

  (import `compute_everify_pending` from `automation.return_status` at the top of `ui/dialogs.py`, or lazily in the method if the module-level import is undesirable).
- Update the hint text to mention the audit report now reflects the portal, with a local downloaded-forms fallback.

- [x] **Step 4: Run, expect pass** — `-k "tab_"` PASS.

- [x] **Step 5: Commit**

```
git add ui/dialogs.py tests/test_return_status.py
git commit -m "feat(return-status): decomposed status + audit report filters (#121)"
```

---

## Task 6: Wire the portal audit probe from the tab (background, non-blocking)

**Files:**
- Modify: `ui/dialogs.py` (`ReturnStatusTab.__init__` + a `set_audit_report_results` method)
- Modify: `app.py` (`_mk_it_return_status_tab` passes a probe callback; implement `start_audit_probe`)

- [x] **Step 1:** Add `audit_probe=None` param to `ReturnStatusTab.__init__`, stored as `self._audit_probe`. Add:

```python
    def set_audit_report_results(self, results: dict):
        """Apply {pan: bool|None} audit-report states from a portal probe."""
        self._audit_report_by_pan.update(results or {})
        self._refresh_table()

    def probe_audit(self):
        """Ask the parent to run the portal audit probe for audit-applicable
        clients of the selected AY. No-op if no callback was supplied."""
        if not self._audit_probe:
            return
        ay = self._current_ay()
        pans = [r["pan"] for r in self._client_rows() if r["audit_on"]]
        if ay and pans:
            self._audit_probe(ay, pans)
```

- [x] **Step 2:** In `app.py::_mk_it_return_status_tab`, pass `audit_probe=self.start_audit_probe`.

- [x] **Step 3:** Implement `start_audit_probe(self, ay_value, pans)` modelled on `start_return_status_check`:
  - Register `_audit_probe_done_signal = pyqtSignal(dict)` next to `_return_status_done_signal` (app.py:265) and connect it in `__init__` to a new `_on_audit_probe_done(self, results)` that calls `self._retstatus_tab.set_audit_report_results(results)` (guard with `getattr`).
  - Guard against overlapping runs with a `self._audit_probe_running` flag; if already running, return.
  - Spawn a daemon thread running an asyncio loop; per PAN: `login_itd(...)`, `await navigate_to_filed_forms(page, self.log)`, `await probe_audit_report(page, step)`, then `await logout_itd(...)`; collect `results[pan] = True/False`. On any per-PAN exception store `None` (None => tab keeps the local-disk fallback). Emit `_audit_probe_done_signal.emit(results)` from `finally`, clear the running flag.
  - Import `probe_audit_report` (from `automation.return_status`) and `navigate_to_filed_forms` (from `automation.downloader_filed_forms`) lazily inside the worker. Reuse `make_step_logger` for `step`.
  - Add a small "Audit reports" refresh button (`self._btn_audit_probe`) next to "Fetch Selected" in `ui/dialogs.py` that calls `self.probe_audit()`; also call `self.probe_audit()` once after `refresh()` when any row has `audit_on` (deferred via `QTimer.singleShot(0, ...)` so the tab paints first).

- [x] **Step 4: Smoke check (no portal)**

Run: `QT_QPA_PLATFORM=offscreen .../python -c "import app"` → imports OK.

- [x] **Step 5: Commit**

```
git add ui/dialogs.py app.py
git commit -m "feat(return-status): background portal audit-report probe (#121)"
```

---

## Task 7: Retire the legacy ReturnStatusDialog menu entry

**Files:**
- Modify: `app.py:639-643` (menu)
- Modify: `app.py:6296-6301` (`_open_return_status_dialog`)

- [x] **Step 1:** Repoint the "Return Status" menu action to the existing inline hub tab instead of the modal. Rename the action to `"Open Return Status tab"` and connect it to a new `self._open_return_status_tab` that does: `self._nav_shell.go("it")` then `self._switch_it_tab(3)` (index 3 = Return Status in `labels` at app.py:3448). Both helpers already exist (`_nav_shell.go`, `_switch_it_tab`).

- [x] **Step 2:** Delete `_open_return_status_dialog` (app.py:6296-6301). Remove `ReturnStatusDialog` from the `from ui.dialogs import ...` block (app.py:48) **only after** `grep -n "ReturnStatusDialog" app.py` shows the import line is the last remaining reference. Leave the `ReturnStatusDialog` class itself in `ui/dialogs.py` in place (dead but harmless) — removing the class is out of scope and risks breaking `ReturnStatusProgressDialog` imports.

- [x] **Step 3: Verify**

Run: `grep -n "ReturnStatusDialog\|_open_return_status_dialog" app.py` → no hits.
Run: `QT_QPA_PLATFORM=offscreen .../python -c "import app"` → OK.

- [x] **Step 4: Commit**

```
git add app.py
git commit -m "refactor(return-status): retire legacy dialog menu entry (#121)"
```

---

## Task 8: Confirm section derivation is honest; add a test guard

**Files:**
- Modify: `automation/return_status.py` (docstring only — keep `# UNCONFIRMED`)
- Test: `tests/test_return_status.py` (`test_extract_section` already asserts the regex — keep as guard)

- [x] **Step 1:** No behaviour change; update the `_extract_section` docstring to state explicitly that it is a best-effort heuristic pending a real-export confirmation, and that blank is the honest result when no `u/s`/`section`/`NNN(n)`-style clause is present.

- [x] **Step 2:** Run `-k section` → PASS (already covered).

- [x] **Step 3: Commit**

```
git add automation/return_status.py
git commit -m "docs(return-status): clarify best-effort section extraction (#121)"
```

---

## Task 9: Full verification + push upstream prep

- [ ] **Step 1:** Full test file: `.../python -m pytest tests/test_return_status.py -q` → all pass.
- [ ] **Step 2:** Existing suites: `.../python -m pytest test_filed_forms.py test_f14_skip.py test_no_real_identifiers.py -q` → pass.
- [ ] **Step 3:** Compile all touched files: `python -m py_compile app.py ui/dialogs.py automation/return_status.py automation/downloader_filed_returns.py automation/batch_handlers.py vault.py` → OK.
- [ ] **Step 4:** Note in the plan the remaining "ship upstream" step (push `fix/121-return-status-complete` and open a PR to `dkbholusaria/AayDocCapio`) — **only on user request** (no auto-push).
- [ ] **Step 5: Commit** any leftover fixes.

---

## Self-review notes
- Scope check: 7 focused tasks, one subsystem — fine for a single plan.
- Placeholder scan: none ("TBD"/"TODO" absent).
- Consistency: `everify_pending` name used identically in vault, scanner, UI, app.
- Ambiguity: "audit filed/not-filed" filter defined as two independent checkboxes on `r["audit_report"] is True/False`.
