# AayDocCapio — Developer Guide for Claude

AayDocCapio is a PyQt6 desktop app for Indian CAs and tax professionals. It automates bulk download of Form 26AS, AIS, and TIS from the ITD e-Filing portal (`eportal.incometax.gov.in`) using Playwright browser automation. All client credentials are stored locally in an AES-128 encrypted vault — nothing is uploaded anywhere.

**Current version:** read from `version.py` — single source of truth.
**Git workflow:** commit directly to `main`, no feature branches. Push via `gh` token.

---

## Project Layout

```
AayDocCapio/
├── app.py                      # Single-file UI — main window, all Qt widgets
├── version.py                  # Single source of truth: __version__ = "X.Y.Z"
├── themes.py                   # ThemeColors dataclass, light/dark theme builders
├── vault.py                    # Encrypted client vault (AES-128 Fernet)
├── config.py                   # App paths (_app_dir, _default_download_dir)
├── utils.py                    # Shared utilities (get_timestamp, etc.)
├── as26_converter.py           # 26AS TXT → Excel + HTML converter
├── assessment_years.json       # AY list with enabled/disabled flags
├── requirements.txt            # Runtime pip dependencies
├── automation/
│   ├── auth.py                 # ITD portal login (Playwright, async)
│   ├── browser.py              # Chrome/Chromium launch + context factory
│   ├── downloader.py           # Batch orchestrator, per-client worker
│   ├── downloader_26as.py      # Form 26AS download flow
│   ├── downloader_ais_tis.py   # AIS + TIS download flow (see details below)
│   └── pdf_unlocker.py         # pikepdf-based PDF password remover
├── ui/
│   ├── widgets.py              # Reusable Qt widgets
│   ├── dialogs.py              # Modal dialogs
│   └── helpers.py              # UI helper functions
├── scripts/
│   ├── bump.sh                 # Version bump helper
│   ├── release.sh              # Full release automation (Linux/WSL)
│   ├── setup.sh                # Dev environment setup (Linux/macOS)
│   ├── setup_and_build.ps1     # Windows build (Nuitka + Inno + WiX)
│   ├── installer.iss           # Inno Setup script (EXE installer)
│   └── installer.wxs           # WiX MSI script
├── resources/                  # Icons, fonts, installer graphics
├── docs/                       # GitHub Pages landing page (index.html)
└── Documentation/              # ADRs, PRD, build guides, backlog
```

---

## Key Architecture Decisions

- **PyQt6** for UI — `QTableWidget` for client grid, `QDialog` for modals, stylesheet-based theming. Do not switch to tkinter or CustomTkinter.
- **Playwright async** for browser automation — each client gets an isolated `BrowserContext`. Never share contexts between clients.
- **Real Google Chrome** (`channel="chrome"`) is required for AIS/TIS downloads. Bundled Chromium silently fails on the AIS portal. 26AS works with either.
- **Fixed viewport 1600×900** — the ITD portal layout breaks at narrower sizes.
- **`asyncio.run()` in a background `QThread`** — keeps the Qt event loop alive during downloads. Never call Qt widgets from the worker thread; use signals.
- **`selected_ids` set** is the source of truth for client selection state. Checkbox visual state and count label must always be derived from this set, never the other way around.
- **Theme detection** — use `getattr(_t(), "name", "").lower() != "light"` to check for dark mode. `_t()` returns the active `ThemeColors` instance.

---

## AIS / TIS Download Flow

### Two phases

**Phase 1 — `run_request_ais()` in `downloader_ais_tis.py`**
- Opens the AIS portal, selects the FY, clicks "Request PDF"
- If AIS is ready instantly → downloads it, unlocks it
- Also downloads TIS immediately (TIS is always available at request time)
- Ends by calling `status_callback(combined_status_label(ais_outcome, tis_outcome))`
- Returns the `ais_outcome` dict with `ais_outcome["tis"] = tis_outcome`

**Phase 2 — `run_download_ais_tis()` in `downloader_ais_tis.py`**
- Used when Phase 1 queued AIS for generation ("Activity History" mode)
- Fetches AIS PDF from the Activity History section
- Ends by calling `status_callback(combined_status_label(ais_outcome, tis_outcome))`
- Returns `{"ais": ais_outcome, "tis": tis_outcome}`

### Outcome dict pattern

Every document result is a dict created by `_outcome()`:

```python
def _outcome(status, unlocked=None, reason=None, **extra):
    return {"status": status, "unlocked": unlocked, "reason": reason, **extra}
```

**Status values:** `"downloaded"`, `"requested"`, `"too_large"`, `"no_data"`, `"not_found"`, `"timeout"`, `"aborted"`, `"skipped"`, `"already_present"`, `"failed"`

**`unlocked` field:** `True` = PDF unlocked, `False` = unlock failed (wrong password), `None` = not attempted

### Status display

```python
def _doc_label(o, name):   # e.g. "AIS" or "TIS"
    # Returns e.g. "✅ AIS unlocked", "⚠️ TIS locked — wrong password", "⬜ AIS — no data for this FY"

def combined_status_label(ais_o, tis_o):
    # Returns e.g. "⚠️ AIS locked — wrong password | ✅ TIS unlocked"
```

### Critical detection order in AIS polling loop

When polling the modal for AIS status, check in this exact order:
1. `"don't have any|do not have any"` → `_outcome("no_data")` — MUST be first
2. `"too large|unable to generate as pdf"` → `_outcome("too_large")` — but NOT `"ais utility"` (that string is always present in modal)
3. `"reference id|activity history|submitted successfully"` → `_outcome("requested")`

### `_download_modal_row()` return type

Returns a **dict**, not a bool:
```python
{"ok": True}                                          # success
{"ok": False, "status": "no_data", "reason": "..."}  # no data
{"ok": False, "status": "failed",  "reason": "..."}  # error
```

---

## Status Callback Architecture

There are TWO distinct `set_status` functions in `app.py` — don't confuse them:

### Local `set_status(pan, text)` — inside the batch runner
```python
def set_status(pan, text):
    if self._progress_dialog:
        self._progress_dialog.set_status(pan, text)          # updates batch progress dialog
    terminal = ("✅", "❌", "🕐", "⏹", "⬜", "⚠")           # ⚠ is REQUIRED here
    if ay_label and any(text.startswith(p) for p in terminal):
        self.vault.record_download(pan, ay_label, text, path) # persists to vault
```

**Critical:** The `⚠` prefix MUST be in the terminal list. Without it, `"⚠️ AIS locked — wrong password | ⚠️ TIS locked — wrong password"` never gets saved to the vault, so the main grid keeps showing the old status from a previous run.

### `self.set_status(pan, text)` — method on the progress dialog widget
- Thread-safe: emits `_update_signal` → updates main batch grid via Qt signal
- This is different from the local function above

### What updates what
| Component | Updated by |
|---|---|
| Batch progress dialog | local `set_status` → `self._progress_dialog.set_status()` |
| Vault (persisted status) | local `set_status` → `vault.record_download()` when terminal prefix |
| Main clients grid "Last Download Status" | reads vault at `refresh_grid()` time |

---

## PDF Unlock

**Password format (ITD convention):**
- AIS / TIS: `lowercase_pan + DDMMYYYY` e.g. `aekpb0205l12121976`
- Form 26AS: `DDMMYYYY` (DOB only, no PAN)

**9 candidates tried** (`pdf_unlocker.py`):
3 DOB formats × 3 PAN variants:
- DOB formats: `DDMMYYYY`, `DDMMYY`, `DD/MM/YYYY`
- PAN variants: lowercase PAN + DOB, DOB only, UPPERCASE PAN + DOB

**Vault stores DOB as `DD-MM-YYYY`** (e.g. `12-12-1976`). The `_dob_variants()` function converts this to the three formats above.

**Common failure:** DOB stored in vault doesn't match what ITD used when the account was registered. Fix: update the DOB in the vault to match the PAN card exactly.

---

## Vault

`vault.py` — AES-128 Fernet encryption, stored in `tax_vault.json`.

Key methods:
```python
vault.get_clients()                          # → list of {pan, name, password, dob, ...}
vault.save_client(pan, name, pwd, dob)       # add/update
vault.record_download(pan, ay, status, path) # persist download status
vault.get_download_history(ay_label)         # → {pan: {status, path, ts}}
```

`get_download_history(ay_label)` is called at `refresh_grid()` to populate the "Last Download Status" column in the main clients grid.

---

## Versioning

**Single source of truth:** `version.py`

```python
__version__ = "1.5.6"   # ← only file to edit when bumping
```

Everything else reads from it:
- `app.py`: `from version import __version__ as APP_VERSION`
- CI workflows: `python -c "from version import __version__; print(__version__)"`
- `installer.iss`: accepts `/DMyAppVersion=` flag from CI (fallback: `"dev"`)
- `installer.wxs`: accepts `-d Version=` flag from CI (`$(var.Version)`)
- `setup_and_build.ps1`: reads via regex on `version.py`

**To bump version:**
```bash
bash scripts/bump.sh patch    # X.Y.Z → X.Y.(Z+1)
bash scripts/bump.sh minor    # X.Y.Z → X.(Y+1).0
bash scripts/bump.sh 1.6.0    # exact version
```

---

## Release Workflow

```bash
# 1. Make and commit all code changes to main

# 2. Bump version
bash scripts/bump.sh patch

# 3. Build Windows installers on Windows (run from PowerShell on Windows machine):
powershell -ExecutionPolicy Bypass -File "\\wsl.localhost\Ubuntu-24.04\home\deepak\projects\AayDocCapio\scripts\setup_and_build.ps1"
# Output: C:\AayDocCapio-build\installer_output\AayDocCapio_Setup_vX.Y.Z.{exe,msi}

# 4. Run the release script from WSL:
bash scripts/release.sh
# Does: changelog via Claude CLI → update docs/index.html → commit → tag → push
#       → create GitHub Release → upload Windows installers → trigger macOS CI
```

**Re-run without a new tag (e.g. to re-upload files):**
```bash
bash scripts/release.sh --rerun
```

**Dry run:**
```bash
bash scripts/release.sh --dry-run
```

### Upload a specific file to an existing release
```bash
gh release upload vX.Y.Z /path/to/file.exe /path/to/file.msi --repo dkbholusaria/AayDocCapio --clobber
```

### Branch naming
- `main` — active development
- `release/vX.Y.Z` — snapshot branch per release

---

## Dev Environment Setup

### Linux / macOS / WSL (run from source)

```bash
bash scripts/setup.sh        # creates .venv, installs deps, installs Playwright Chromium
source .venv/bin/activate
python app.py
```

### Windows (run from source)
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python app.py
```

> AIS/TIS downloads also require real Google Chrome installed. 26AS works with bundled Chromium.

---

## Runtime Dependencies

| Package | Purpose |
|---|---|
| `PyQt6>=6.11.0` | Desktop GUI framework |
| `playwright>=1.60.0` | Browser automation |
| `cryptography>=48.0.0` | AES-128 Fernet vault encryption |
| `pikepdf>=10.7.2` | PDF password removal |
| `openpyxl>=3.1.5` | Excel bulk-import / vault template generation |
| `xlsxwriter>=3.2.0` | 26AS converter — streaming writer for large files |
| `pillow>=12.2.0` | Custom checkbox image generation |

---

## Windows Build Prerequisites

| Tool | Purpose | How to get |
|---|---|---|
| Nuitka | Python → native exe | `pip install nuitka ordered-set zstandard` |
| Inno Setup 6+ | `.exe` installer | jrsoftware.org/isdl.php |
| .NET 8 SDK | Required by WiX | dotnet.microsoft.com/download |
| WiX Toolset v4+ | `.msi` installer | `dotnet tool install --global wix` |
| WixToolset.UI.wixext | Wizard UI | `wix extension add WixToolset.UI.wixext --global` |

**WiX EULA must be accepted before extension add:**
```powershell
wix eula accept wix7
wix extension add WixToolset.UI.wixext --global
```

---

## Coding Conventions

### Theme-aware colors

Always use `ThemeColors` fields — never hardcode hex colors:

```python
from themes import _t
_bt = _t()
item.setForeground(QColor(_bt.text_primary))
item.setBackground(QColor(_bt.bg_table))
```

For status colors: use `(light_fg, dark_fg)` tuple per value:
```python
is_dark = getattr(_t(), "name", "").lower() != "light"
fg = dark_fg if is_dark else light_fg
```

### Selection state

`self.selected_ids` (a `set`) is always the authoritative selection state. Never modify it during row filtering — only hide rows. `_update_count()` counts `selected_ids ∩ visible_rows`.

### Thread safety

Download workers run in a `QThread`. Update UI only via Qt signals — never call widget methods from a worker thread directly.

### Error messages

`_friendly_error(raw)` in `app.py` maps raw exception messages to user-readable strings. Add new portal-specific error patterns here.

---

## Assessment Years

Controlled by `assessment_years.json`. Set `"enabled": true` to make an AY available in the UI. Read at startup — no code change needed to add a new year.

---

## Maintenance Detection

`automation/auth.py` reads `page.inner_text("body")` after navigation and checks for: `"maintenance"`, `"website will be down"`, `"maintance"` (portal typo). Raises `RuntimeError` with the maintenance window text extracted from the page.

---

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| AIS/TIS downloads silently fail | Must use `channel="chrome"` (real Chrome), not bundled Chromium |
| `expect_download` never fires | Call it on `Page`, not `BrowserContext` |
| Portal never reaches `networkidle` | Use `wait_until="domcontentloaded"` + `asyncio.sleep(3)` |
| AIS "no data" misclassified as "queued" | Check `"don't have any"` BEFORE `"activity history"` in the polling loop |
| AIS always flagged "too large" | Don't include `"ais utility"` in the too-large regex — it's always present in the modal |
| `⚠️` statuses not shown in main grid | `"⚠"` must be in terminal prefixes in local `set_status` |
| PDF unlock fails | Verify DOB in vault matches PAN card exactly (DD-MM-YYYY format) |
| Checkbox count wrong after filter | Never modify `selected_ids` in `_apply_filter` |
| Dark theme text unreadable | Use `ThemeColors` fields, not hardcoded hex |
| WiX `wix` not found after install | Add `$env:USERPROFILE\.dotnet\tools` to PATH |
| WiX fails with EULA error | Run `wix eula accept wix7` before `wix extension add` |
| Nuitka missing module at runtime | Add `--include-package=automation` or `--include-module=<name>` |
