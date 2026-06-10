# AayDocCapio

**v1.2.0** — A secure, standalone desktop utility for **bulk downloading Form 26AS, AIS, and TIS** from the [Income Tax Department e-Filing portal](https://eportal.incometax.gov.in) for multiple clients in one click.

Built with **PyQt6** + **Playwright**. Runs on Windows, macOS, and Linux/WSL.

---

## What's New in 1.2.0

- **Light / Dark Navy theme** — Settings → Appearance; persisted across sessions
- **Redesigned UI** — full-width client table, menu bar (Client Master / Settings), settings bar
- **Last Download Status & Last Saved Location** columns in the client table
- **Add/Edit client as popup dialog** — no more side panel
- **••• row action menu** — Edit and Delete per client row
- **Download history per Assessment Year** — status and path stored in vault per client/year
- **User-friendly error messages** — plain English for portal/network errors
- **Per-row timestamps** in the Excel download report

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
`AayDocCapio.command` in Finder — see the [macOS guide](Documentation/macos_support.md).

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
app.py          — Main window, all UI logic
themes.py       — ThemeColors dataclass, THEMES registry, build_stylesheet()
vault.py        — Encrypted client vault, settings, download history
automation/     — Playwright automation scripts (26AS, AIS, TIS)
resources/      — Icons, checkmark image
assessment_years.json  — AY/TY list (editable via Settings → Manage Years)
```

---

## Requirements

- Python 3.11+
- Google Chrome (for AIS/TIS; Chromium suffices for 26AS)
- See `requirements.txt` for Python packages
