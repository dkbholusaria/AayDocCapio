# AayDocCapio

**v1.6.4** — A secure, standalone desktop utility for **bulk downloading Form 26AS, AIS, and TIS** from the [Income Tax Department e-Filing portal](https://eportal.incometax.gov.in) for multiple clients in one click — and now **emailing those documents directly to clients**.

Built with **PyQt6** + **Playwright**. Runs on Windows, macOS, and Linux/WSL.

---

## What's New in 1.6.4

- **Expanded Interactive User Manual** — Upgraded the integrated HTML user manual to feature 37 nested navigation sub-sections in a left sidebar with robust scrollspy tracking, rebranded "Client Vault" to "Managing Clients" (with nested bulk import/export guidelines), and added step-by-step guides for SMTP email setup, bulk downloads, and software auto-update procedures.
- **Last Download Time Column** — Added a dedicated column in the main client table to display the timestamp of the last successful download, persisted in the vault (`tax_vault.json`).
- **Non-existent PAN Fast-Fail** — Detects non-registered/invalid PAN errors immediately on the ITD portal and aborts the task with a clean warning instead of waiting for a timeout.

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
| Managing Clients | Encrypted credentials (AES-256 via Fernet) |
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
