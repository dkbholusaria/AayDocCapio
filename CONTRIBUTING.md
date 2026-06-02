# Contributing

## Reporting issues

Please open a GitHub Issue with:
- Steps to reproduce
- Expected vs actual behaviour
- Python version and OS
- Relevant log output (copy from the live log console via the **Copy** button — logs contain no credentials)

## Development setup

```bash
git clone https://github.com/dkbholusaria/ITD-docs-downloader.git
cd ITD-docs-downloader
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python app.py
```

## Key files

| File | Purpose |
|---|---|
| `app.py` | All UI code (PyQt6) |
| `vault.py` | Encryption, CRUD, import/export |
| `automation/auth.py` | ITD portal login / logout |
| `automation/downloader_26as.py` | TRACES / Form 26AS flow |
| `automation/downloader_ais_tis.py` | Compliance Portal AIS/TIS flow |

## Security rules (non-negotiable)

- PAN numbers must **never** appear in log messages, error dialogs, or exception strings
- `tax_vault.json` must remain in `.gitignore` — never commit it
- Do not add any outbound network calls outside of the ITD portal domains
