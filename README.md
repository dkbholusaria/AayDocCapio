# ITD Docs Downloader

A secure, standalone desktop utility for **bulk downloading Form 26AS, AIS, and TIS** from the [Income Tax Department e-Filing portal](https://eportal.incometax.gov.in) for multiple clients in one click.

Built with **PyQt6** + **Playwright**. Runs on Windows and Linux/WSL.

---

## Features

- **Encrypted credential vault** — PAN, DOB, and portal passwords stored locally using PBKDF2HMAC + Fernet AES-128; never sent anywhere
- **Bulk operations** — import assessees from Excel/CSV, export saved records, generate import templates
- **One-click batch download** — logs in, downloads, logs out sequentially for every selected client
- **Documents supported** — Form 26AS (PDF + TXT), AIS (PDF + JSON), TIS (PDF)
- **Assessment year management** — add/remove/toggle years via the built-in Manage Years dialog
- **Live log console** — real-time status feed during automation runs
- **Search / filter** — filter client list by name or PAN

---

## Screenshots

> _Add screenshots here after first run_

---

## Project Structure

```
ITD-docs-downloader/
├── app.py                        # PyQt6 main application
├── vault.py                      # Encrypted credential vault manager
├── assessment_years.json         # Configured assessment / tax years
├── requirements.txt              # Python dependencies
├── automation/
│   ├── browser.py                # Playwright browser manager (self-healing Chromium)
│   ├── auth.py                   # ITD login / logout automation
│   ├── downloader.py             # Shared download utilities
│   ├── downloader_26as.py        # Form 26AS download logic (TRACES)
│   └── downloader_ais_tis.py     # AIS / TIS download logic (Compliance Portal)
├── resources/
│   ├── check.png                 # Checkbox tick icon
│   └── chevron_down.png          # Dropdown arrow icon
├── build_win.bat                 # Windows PyInstaller build script
└── outputs/                      # Downloaded files (created at runtime)
    └── <PAN>-<Name>/
        └── AY_<year>/
            ├── 26AS-*.pdf
            ├── 26AS-*.txt
            ├── AIS-*.pdf
            ├── AIS-*.json
            └── TIS-*.pdf
```

---

## Installation

### Prerequisites

- Python 3.10+
- pip

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/dkbholusaria/ITD-docs-downloader.git
cd ITD-docs-downloader

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Linux / WSL
# .venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright's Chromium browser
playwright install chromium

# 5. Run the app
python app.py
```

---

## Usage

### Add a client manually
1. Open the **Single Profile** tab in the left panel
2. Fill in Full Name, PAN Number, Date of Birth (DD-MM-YYYY), and Portal Password
3. Click **Save Profile**

### Bulk import clients
1. Open the **Bulk Operations** tab
2. Click **Generate Upload Template** to download a pre-formatted Excel file
3. Fill in the template (Name, PAN, DOB, Password columns)
4. Click **Import CSV / Excel** to load all records into the vault

### Download documents
1. Select an **Assessment Year** from the settings bar
2. Tick the document types to download (26AS / AIS / TIS)
3. Set the **Output Directory** (defaults to `outputs/` inside the project folder)
4. Check one or more clients from the list (or use **Select / Deselect All**)
5. Click **▶ Start Download**

Downloaded files are saved to:
```
<Output Directory>/<PAN>-<Client Name>/AY_<year>/
```

---

## Security

| Concern | How it's handled |
|---|---|
| Credential storage | AES-128 (Fernet) encrypted local JSON file (`tax_vault.json`) |
| Key derivation | PBKDF2HMAC / SHA-256, 100,000 iterations |
| PAN in error messages | PAN is **never** included in error or log output |
| Vault file in git | `tax_vault.json` is in `.gitignore` and will never be committed |
| Network | Credentials are only submitted to the official ITD portal; no third-party services involved |

---

## Import File Format

| Column | Format | Example |
|---|---|---|
| Name | Text | John Doe |
| PAN | 10-char alphanumeric | AAAPT0001A |
| DOB | DD-MM-YYYY (or DD/MM/YYYY, DD.MM.YYYY, ISO) | 01-01-1980 |
| Password | Text | MyPortalPass@1 |

---

## Building a Windows Executable

On a Windows machine with Python installed:

```bat
build_win.bat
```

This runs PyInstaller and produces `dist/TaxDownloader.exe` — a single-file standalone executable with no Python installation required on the target machine.

---

## Known Limitations

- AIS/TIS portal selectors may need updates if the ITD Compliance Portal UI changes
- Logout occasionally fails with "Profile menu not found" — the session is still terminated safely
- MSI/installer packaging not yet implemented (executable only)

---

## License

MIT License — see [LICENSE](LICENSE) for details.
