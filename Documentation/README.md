# ITD Docs Downloader

A secure, standalone desktop utility for **bulk downloading Form 26AS, AIS, and TIS** from the [Income Tax Department e-Filing portal](https://eportal.incometax.gov.in) for multiple clients in one click.

Built with **PyQt6** + **Playwright**. Runs on Windows and Linux/WSL.

---

## Features

- **Encrypted credential vault** — PAN, DOB, and portal passwords stored locally using PBKDF2HMAC + Fernet AES-128; never sent anywhere
- **Bulk operations** — import assessees from Excel/CSV, export saved records, generate import templates
- **One-click batch download** — logs in, downloads, logs out sequentially for every selected client
- **Documents supported** — Form 26AS (PDF + TXT), AIS (PDF), TIS (PDF)
- **Run dropdown** — single ▶ Run button with: Download 26AS · Download / Request TIS & AIS · Download Previously Requested AIS
- **Live per-client progress popup** — a modal dialog shows one row per client with live status; Stop control lives here
- **Assessment year management** — add/remove/toggle years via the built-in Manage Years dialog
- **Per-client error isolation** — one client's failure (e.g. wrong password) never aborts the batch; the reason is shown in the row, the summary dialog, and the live log
- **Comprehensive step logging** — every automation step is logged with a numbered counter and URL for easy diagnosis
- **Search / filter** — filter client list by name or PAN

> **Important:** AIS/TIS downloads require **Google Chrome** to be installed.
> The app launches real Chrome (`channel="chrome"`); the Insight/AIS portal's
> download buttons do not work under Playwright's bundled Chromium. 26AS works
> with either. See the [Development Log](DEVELOPMENT_LOG.md) for the full reason.

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
│   ├── browser.py                # Playwright manager (prefers real Google Chrome)
│   ├── auth.py                   # ITD login / logout automation
│   ├── downloader.py             # Shared utilities + step logger
│   ├── downloader_26as.py        # Form 26AS download logic (TRACES)
│   └── downloader_ais_tis.py     # AIS / TIS download logic (Insight portal)
├── resources/                    # UI icons
├── scripts/
│   ├── setup_and_build.ps1       # Windows sync + Nuitka build + Inno Setup
│   ├── installer.iss             # Inno Setup installer script
│   └── setup.sh                  # Linux/WSL dev setup
├── Documentation/
│   ├── README.md                 # This file
│   ├── DEVELOPMENT_LOG.md        # Design decisions + debugging history
│   ├── CONTRIBUTING.md
│   ├── implementation_plan.md
│   └── walkthrough.md
└── outputs/                      # Downloaded files (created at runtime)
    └── <PAN>-<Name>/
        └── AY_<year>/
            ├── <PAN>-26AS-*.pdf
            ├── <PAN>-26AS-*.txt
            ├── <PAN>-AIS-<FY>.pdf
            └── <PAN>-TIS-<FY>.pdf
```

---

## Installation

### Prerequisites

- Python 3.10+
- pip
- **Google Chrome** installed (required for AIS/TIS downloads)

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

# 4. Install browsers
#    - Real Google Chrome is used at runtime (channel="chrome").
#    - Playwright's Chromium is the fallback (26AS only).
playwright install chromium       # fallback engine
playwright install chrome         # or install Google Chrome system-wide

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
2. Set the **Output Directory** (defaults to `outputs/` inside the project folder)
3. Check one or more clients from the list (or use **Select / Deselect All**)
4. Click **▶ Run** and choose:
   - **Download 26AS** — Form 26AS PDF + TXT (TRACES)
   - **Download / Request TIS & AIS** — AIS PDF + TIS PDF (Insight portal)
   - **Download Previously Requested AIS** — fetch a queued large AIS from Activity History
5. A **Batch Progress** popup shows live per-client status; use its **Stop** button to abort

Downloaded files are saved to:
```
<Output Directory>/<PAN>-<Client Name>/AY_<year>/
```

> A live status badge is also injected at the top of the automated browser
> window so you can watch each step as it happens.

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

On a Windows machine (with the project synced from WSL), run from PowerShell:

```powershell
scripts\setup_and_build.ps1
```

This script:
1. Syncs the project from WSL to `C:\ITD-build`
2. Creates a venv and installs dependencies
3. Compiles with **Nuitka** (native machine code) to `dist\TaxDownloader\`
4. Packages an installer with **Inno Setup** → `installer_output\ITDDocsDownloader_Setup_*.exe`

> The build uses Nuitka (not PyInstaller). The installer also pre-installs the
> Playwright Chromium fallback during setup.

---

## Known Limitations

- **AIS/TIS require Google Chrome** — the Insight portal's download buttons only
  fire on real Chrome (`channel="chrome"`). Without Chrome, only 26AS works.
- AIS JSON is intentionally skipped (the portal gates it behind a CAPTCHA).
- AIS/Insight portal selectors may need updates if the portal UI changes — the
  step logs make this easy to diagnose.
- PDF password removal is not yet implemented (downloaded AIS/TIS PDFs are
  password-protected: PAN in lowercase + DOB `ddmmyyyy`).

For the full design history and root-cause analysis of the AIS download work,
see **[DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)**.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
