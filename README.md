# AayDocCapio

**v1.5.6** — A secure, standalone desktop utility for **bulk downloading Form 26AS, AIS, and TIS** from the [Income Tax Department e-Filing portal](https://eportal.incometax.gov.in) for multiple clients in one click — and now **emailing those documents directly to clients**.

Built with **PyQt6** + **Playwright**. Runs on Windows, macOS, and Linux/WSL.

---

## What's New in 1.5.6

### Email Delivery — Complete Workflow
Tax professionals can now email downloaded documents to clients without leaving the app:

- **Mail Docs to Clients** — one-click access from the new **Email Docs** button on the main toolbar, or via Tools menu
- **Scan & match** — point to your download folder; the app finds each client's AIS/TIS/26AS files automatically
- **Numbered document list** — email body renders `{documents}` as a numbered HTML list (Form 26AS PDF, Form 26AS Excel, AIS, TIS — only the files that actually exist)
- **Batch send** — select any subset of clients and send in one go with per-row live status (⏳ Sending → ✅ Sent / ❌ Failed)
- **Inline email editing** — type or correct a client's email address directly in the table; saved to vault automatically before sending
- **Filter, sort, select** — search by name/PAN/email, sort any column, Select All/None respects active filter
- **"Powered by AayDocCapio"** footer appended automatically to every outgoing email (non-editable)
- **Session log dividers** — email log now shows clear `── SESSION STARTED ──` / `── SESSION ENDED ──` separators between app sessions

### Email Provider Support
Full SMTP configuration with one-click presets for all major providers:

| Provider | Host | Notes |
|---|---|---|
| **Gmail** | smtp.gmail.com:587 | Requires App Password (2FA) |
| **Outlook.com / Hotmail** | smtp-mail.outlook.com:587 | App Password if MFA enabled |
| **Microsoft 365 / Office 365** | smtp.office365.com:587 | SMTP AUTH must be enabled by admin |
| **Exchange (on-premise)** | your server | Enter host manually |
| **Yahoo Mail** | smtp.mail.yahoo.com:587 | Requires App Password |
| **iCloud Mail** | smtp.mail.me.com:587 | Requires App-Specific Password |
| **Custom / Other** | any | Full manual configuration |

Each preset auto-fills host/port/encryption and shows provider-specific setup instructions with clickable links.

### UI Improvements
- **Download button** — "Run" renamed to "Download" for clarity
- **Email Docs button** — quick-launch on main toolbar (no menu navigation needed)
- **Exit button** — one-click close with clean session-end logging
- **Rich text email composer** — font, size, bold/italic/underline, placeholders as chips
- **Premium help notes** — blue left-bordered info panels with clickable links throughout Email Settings
- **Fluency multicolor icons** — all buttons, menus, and context menus now have icons

### Bug Fixes
- Batch send silent crash when HTML email body contained CSS `{}` braces
- Mail Docs sorting now correctly moves all row widgets (checkboxes, email fields, status) together
- Checkbox and inline-edit backgrounds now match table row color (no white flash)

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
| **Email delivery** | **Batch email tax docs to clients with one click** |
| **Provider presets** | **Gmail, Outlook, Office 365, Exchange, Yahoo, iCloud, Custom** |
| **Rich text composer** | **Font, size, B/I/U, placeholders, CC, BCC** |
| Client vault | Encrypted credentials (AES-256 via Fernet) |
| Bulk import | Excel / CSV template with Name, PAN, DOB, Password, Email, CC |
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
  dialogs.py             — ManageYearsDialog, BatchProgressDialog, MailDocsDialog, SmtpSettingsDialog
automation/
  browser.py             — Playwright browser launch / auth helpers
  downloader_26as.py     — 26AS download + TXT → Excel/HTML converter
  downloader_ais_tis.py  — AIS/TIS download
  emailer.py             — SMTP send, batch send, session logging, document list builder
  as26_converter.py      — 26AS TXT parser
  errors.py              — Human-readable error messages
scripts/
  release.sh             — GitHub release automation (--dry-run, --rerun)
  bump.sh                — Version bump utility
  AayDocCapio.command    — macOS double-click launcher
resources/icons/         — All PNG icons (buttons, menus, email providers)
assessment_years.json    — AY/TY list (editable via Settings → Manage Years)
```

---

## Requirements

- Python 3.11+
- Google Chrome (for AIS/TIS; Chromium suffices for 26AS)
- See `requirements.txt` for Python packages
