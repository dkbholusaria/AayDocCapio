# AayDocCapio — Agent & Developer Guide

AayDocCapio is a PyQt6 desktop app for Indian CAs and tax professionals. It automates bulk download of Form 26AS, AIS, and TIS from the ITD e-Filing portal (`eportal.incometax.gov.in`) using Playwright browser automation. All client credentials are stored locally in an AES-128 encrypted vault — nothing is uploaded anywhere.

---

## Project Layout

```
AayDocCapio/
├── app.py                      # Single-file UI — main window, all Qt widgets
├── themes.py                   # ThemeColors dataclass, light/dark theme builders
├── vault.py                    # Encrypted client vault (AES-128 Fernet)
├── as26_converter.py           # 26AS TXT → Excel + HTML converter
├── version.py                  # Single source of truth for version string
├── assessment_years.json       # AY list with enabled/disabled flags
├── requirements.txt            # Runtime pip dependencies
├── automation/
│   ├── auth.py                 # ITD portal login (Playwright, async)
│   ├── browser.py              # Chrome/Chromium launch + context factory
│   ├── downloader.py           # Batch orchestrator, per-client worker
│   ├── downloader_26as.py      # Form 26AS download flow
│   ├── downloader_ais_tis.py   # AIS + TIS download flow
│   └── pdf_unlocker.py         # pikepdf-based PDF password remover
├── scripts/
│   ├── bump.sh                 # Version bump helper
│   ├── release.sh              # Full release automation (Linux/WSL)
│   ├── setup.sh                # Dev environment setup (Linux/macOS)
│   ├── setup_and_build.ps1     # Windows build (Nuitka + Inno + WiX)
│   ├── build_win.bat           # Simple Windows batch build
│   ├── installer.iss           # Inno Setup script
│   └── installer.wxs           # WiX MSI script
├── resources/                  # Icons, fonts, installer graphics
├── docs/                       # GitHub Pages landing page
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

## Dev Environment Setup

### Linux / macOS / WSL (run from source)

```bash
cd /path/to/AayDocCapio
bash scripts/setup.sh        # creates .venv, installs deps, installs Playwright Chromium
source .venv/bin/activate
python app.py
```

Manual steps if you prefer:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
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
| `pikepdf>=10.7.2` | PDF password removal (needs system `qpdf`) |
| `openpyxl>=3.1.5` | Excel bulk-import / vault template generation |
| `xlsxwriter>=3.2.0` | 26AS converter — streaming writer for large files |
| `pillow>=12.2.0` | Custom checkbox image generation |

Install: `pip install -r requirements.txt`

After install: `playwright install chromium` (and optionally `playwright install chrome`)

---

## Windows Build Prerequisites

Required only to produce a distributable `.exe` / `.msi`. Not needed to run from source.

| Tool | Purpose | How to get |
|---|---|---|
| Python 3.12 | Runtime + build | python.org |
| Nuitka | Python → native exe | `pip install nuitka ordered-set zstandard` |
| Inno Setup 6+ | `.exe` installer | jrsoftware.org/isdl.php |
| .NET 8 SDK | Required by WiX | dotnet.microsoft.com/download |
| WiX Toolset v4+ | `.msi` installer | `dotnet tool install --global wix` |
| WixToolset.UI.wixext | Installer wizard UI | `wix extension add WixToolset.UI.wixext --global` |
| Google Chrome | AIS/TIS downloads | google.com/chrome |

### Automated build (recommended)

From WSL, run on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File "\\wsl.localhost\Ubuntu-24.04\home\deepak\projects\AayDocCapio\scripts\setup_and_build.ps1"
```

Output: `C:\AayDocCapio-build\installer_output\AayDocCapio_Setup_v*.exe` and `.msi`

---

## Release Workflow

1. Make code changes and commit normally.
2. Bump the version:
   ```bash
   bash scripts/bump.sh patch    # 1.4.2 → 1.4.3
   bash scripts/bump.sh minor    # 1.4.2 → 1.5.0
   bash scripts/bump.sh 1.5.0    # exact version
   ```
3. Build Windows installers on Windows (see above). They land in `C:\AayDocCapio-build\installer_output\`.
4. Run the release script from WSL:
   ```bash
   bash scripts/release.sh
   ```
   This will: auto-copy installers from C: drive → generate changelog via Claude CLI → update `docs/index.html` → commit → tag → push → create GitHub Release → upload installers → trigger macOS CI.

### Re-run / fix a release (tag already exists)

```bash
bash scripts/release.sh --rerun    # re-uploads installers, re-triggers CI, adds changelog if missing
```

### Dry run (preview without touching anything)

```bash
bash scripts/release.sh --dry-run
```

---

## Coding Conventions

### Theme-aware colors

Always use `ThemeColors` fields — never hardcode hex colors:

```python
from themes import _t
_bt = _t()
item.setForeground(QColor(_bt.text_primary))   # NOT QColor("#1E293B")
item.setBackground(QColor(_bt.bg_table))
```

For status colors where light/dark differ, use a `(light_fg, dark_fg)` tuple dict:

```python
_STATUS_FG = {
    "success": ("#15803D", "#4ADE80"),
    "failed":  ("#B91C1C", "#F87171"),
}
is_dark = getattr(_t(), "name", "").lower() != "light"
fg = dark_fg if is_dark else light_fg
```

### Selection state

`self.selected_ids` (a `set`) is always the authoritative selection state. Checkbox widgets and the count label are views derived from it. When filtering rows:

- **Never** remove IDs from `selected_ids` when hiding rows.
- **Do** re-sync checkbox visual state when rows become visible again.
- `_update_count()` counts `selected_ids ∩ visible_rows` for the label.

### Thread safety

Download workers run in a `QThread`. Update UI only via Qt signals — never call `self.some_widget.setText()` from a worker thread directly.

### Error messages

`_friendly_error(raw)` in `app.py` maps raw exception messages to user-readable strings. Add new portal-specific error patterns here. Maintenance page errors are passed through as-is (they already contain the time window).

---

## Maintenance Detection

`automation/auth.py` detects ITD portal maintenance pages by reading `page.inner_text("body")` after navigation and checking for keywords: `"maintenance"`, `"website will be down"`, `"maintance"` (portal typo). It raises a `RuntimeError` with the maintenance window extracted from the page text.

---

## Assessment Years

Controlled by `assessment_years.json`. Each entry has `"enabled": true/false`. Set `enabled: true` to make an AY available in the UI. The app reads this file at startup — no code change needed to add a new year.

---

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| AIS/TIS downloads silently fail | Must use `channel="chrome"` (real Chrome), not bundled Chromium |
| `expect_download` never fires | Call it on `Page`, not `BrowserContext` |
| Portal never reaches `networkidle` | Use `wait_until="domcontentloaded"` + `asyncio.sleep(3)` |
| Checkbox count wrong after filter | Never modify `selected_ids` in `_apply_filter` — only hide rows |
| Dark theme text unreadable | Use `ThemeColors` fields, not hardcoded hex; use `(light_fg, dark_fg)` tuples for status colors |
| WiX `wix` not found after install | Add `$env:USERPROFILE\.dotnet\tools` to PATH |
| Nuitka missing module at runtime | Add `--include-package=automation` or `--include-module=<name>` to Nuitka flags |
