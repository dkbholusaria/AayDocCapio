# AayDocCapio

A secure, standalone desktop utility for **bulk downloading Form 26AS, AIS, and TIS** from the [Income Tax Department e-Filing portal](https://eportal.incometax.gov.in) for multiple clients in one click.

Built with **PyQt6** + **Playwright**. Runs on Windows, macOS, and Linux/WSL.

---

## Quick Links

- [Full Documentation](Documentation/README.md)
- [Windows Build Guide](Documentation/windows_build.md) — Nuitka, Inno Setup, WiX MSI
- [macOS Support](Documentation/macos_support.md) — setup, what changed, app-bundle build
- [Development Log](Documentation/DEVELOPMENT_LOG.md) — design decisions & debugging history
- [Contributing Guide](Documentation/CONTRIBUTING.md)
- [License](Documentation/LICENSE)

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
