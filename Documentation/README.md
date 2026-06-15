# AayDocCapio

**v1.4.4** — A secure, standalone desktop utility for **bulk downloading Form 26AS, AIS, and TIS** from the [Income Tax Department e-Filing portal](https://eportal.incometax.gov.in) for multiple clients in one click.

Built with **PyQt6** + **Playwright**. Runs on Windows, macOS, and Linux/WSL.

---

## What's New in 1.4.x

- **Status filter dropdown** — filter client grid by All / Downloaded / Partially Completed / Failed / Queued / Not run yet
- **26AS TXT → Excel + HTML converter** — auto-runs after each 26AS batch; also available via Tools menu
- **Form 26AS Excel workbook** — Assessee Details sheet, one sheet per Part (I-IX), Summary sheet with hyperlinks
- **Locked-file fallback** — writes a timestamped alternate file if Excel is open during conversion
- **Large 26AS detection** — TRACES on-demand messages now show a clear actionable error
- **ITD login fix for real Chrome** — avoids waiting forever on background Chrome network activity
- **Modular codebase** — app.py split into `config.py`, `utils.py`, `ui/`, `automation/errors.py`

See the full [CHANGELOG](CHANGELOG.md) for details.

---

## Quick Links

- [Full Documentation](Documentation/README.md)
- [Windows Build Guide](Documentation/windows_build.md) — Nuitka, Inno Setup, WiX MSI
- [macOS Support](Documentation/macos_support.md) — setup, what changed, app-bundle build
- [Development Log](Documentation/DEVELOPMENT_LOG.md) — design decisions & debugging history
- [Changelog](CHANGELOG.md)

---

## Quick Start

```bash
git clone https://github.com/dkbholusaria/AayDocCapio.git
cd AayDocCapio
pip install -r requirements.txt
playwright install chromium
python app.py
```

> **Requires Google Chrome** for AIS/TIS downloads (the app launches real Chrome
> via `channel="chrome"`). 26AS works without it.

On macOS you can also run `bash scripts/setup.sh` once and then double-click
`scripts/AayDocCapio.command` in Finder — see the [macOS guide](Documentation/macos_support.md).

---

## Features

| Feature | Details |
|---|---|
| Form 26AS | PDF + TXT download for all selected clients |
| AIS / TIS | Request generation + download once ready |
| Client vault | Encrypted credentials (AES-256 via Fernet) |
| Bulk import | Excel / CSV template with Name, PAN, DOB, Password |
| Assessment Year management | Toggle years on/off, add custom AY/TY entries |
| Download history | Last status and folder per client per AY, shown in table |
| Themes | Light and Dark Navy; extensible via `themes.py` |
| Resume after Stop | Retry only the clients that were not completed |
| Excel report | Per-client status, folder hyperlink, per-row timestamp |
| Headless mode | Run browser hidden or visible (for CAPTCHA handling) |

---

## Architecture

```
app.py                   — Main window and all application logic
config.py                — Path helpers (_app_dir, _bundled_dir, etc.)
utils.py                 — Shared utilities (timestamps, etc.)
themes.py                — ThemeColors dataclass, THEMES registry, build_stylesheet()
vault.py                 — Encrypted client vault, settings, download history
ui/
  _theme.py              — Shared active-theme state (avoids circular imports)
  helpers.py             — Widget factory helpers (_btn, _lbl, _shadow, _status_style)
  widgets.py             — StyledComboBox and delegates
  dialogs.py             — ManageYearsDialog, BatchProgressDialog
automation/
  browser.py             — Playwright browser launch / auth helpers
  downloader.py          — Form 26AS download
  downloader_26as.py     — 26AS TXT → Excel/HTML converter
  downloader_ais_tis.py  — AIS/TIS download
  as26_converter.py      — 26AS TXT parser
  errors.py              — Human-readable error messages
scripts/
  release.sh             — GitHub release automation (--dry-run, --rerun)
  bump.sh                — Version bump utility
  AayDocCapio.command    — macOS double-click launcher
resources/               — Icons, checkmark image
assessment_years.json    — AY/TY list (editable via Settings → Manage Years)
```

---

## Requirements

- Python 3.11+
- Google Chrome (for AIS/TIS; Chromium suffices for 26AS)
- See `requirements.txt` for Python packages
