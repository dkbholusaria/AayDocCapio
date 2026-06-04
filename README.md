# ITD Docs Downloader

A secure, standalone desktop utility for **bulk downloading Form 26AS, AIS, and TIS** from the [Income Tax Department e-Filing portal](https://eportal.incometax.gov.in) for multiple clients in one click.

Built with **PyQt6** + **Playwright**. Runs on Windows and Linux/WSL.

---

## Quick Links

- [Full Documentation](Documentation/README.md)
- [Development Log](Documentation/DEVELOPMENT_LOG.md) — design decisions & debugging history
- [Contributing Guide](Documentation/CONTRIBUTING.md)
- [License](Documentation/LICENSE)

---

## Quick Start

```bash
git clone https://github.com/dkbholusaria/ITD-docs-downloader.git
cd ITD-docs-downloader
pip install -r requirements.txt
playwright install chromium
python app.py
```

> **Requires Google Chrome** for AIS/TIS downloads (the app launches real Chrome
> via `channel="chrome"`). 26AS works without it.
