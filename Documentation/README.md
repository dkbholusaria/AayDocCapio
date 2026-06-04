# ITD Docs Downloader

A secure, standalone desktop utility for **bulk downloading Form 26AS, AIS, and TIS** from the [Income Tax Department e-Filing portal](https://eportal.incometax.gov.in) for multiple clients in one click.

Built with **PyQt6** + **Playwright**. Runs on Windows and Linux/WSL.

---

## Features

- **Encrypted credential vault** — PAN, DOB, and portal passwords stored locally using PBKDF2HMAC + Fernet AES-128; never sent anywhere
- **Bulk operations** — import assessees from Excel/CSV, export saved records, generate import templates
- **One-click batch download** — logs in, downloads, logs out sequentially for every selected client
- **Documents supported** — Form 26AS (PDF + TXT), AIS (PDF), TIS (PDF)
- **Automated PDF unlocking** — automatically unlocks downloaded PDFs using the client's PAN and DOB.
- **Run dropdown** — single ▶ Run button with: Download 26AS · Download / Request TIS & AIS · Download Previously Requested AIS
- **Headless mode by default** — browsers run invisibly, with a UI toggle ("Show Browser (Debug)") to reveal them for debugging.
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

ITD-docs-downloader/
├── app.py                        # PyQt6 main application GUI and orchestration
├── vault.py                      # Encrypted credential vault manager (Fernet AES-128)
├── app.log                       # Rotating log of runtime events
├── assessment_years.json         # Configured assessment / tax years
├── requirements.txt              # Python dependencies (PyQt6, playwright, pikepdf, etc.)
├── tax_vault.json                # Local encrypted client database (created on run)
├── automation/
│   ├── browser.py                # Playwright manager (handles headless/interactive and browser installs)
│   ├── auth.py                   # ITD login / logout automation and error handling
│   ├── downloader.py             # Shared utilities + live step logger
│   ├── downloader_26as.py        # Form 26AS download logic (TRACES fallback handling)
│   ├── downloader_ais_tis.py     # AIS / TIS download logic (Insight portal modal triggers)
│   └── pdf_unlocker.py           # Automated PDF password unlocking (uses PAN and DOB)
├── resources/                    # UI icons (check.png, chevron_down.png)
├── scripts/
│   ├── setup_and_build.ps1       # Windows sync + Nuitka build + Inno Setup compilation
│   ├── build_win.bat             # Batch script wrapper for building
│   ├── installer.iss             # Inno Setup installer script definition
│   ├── TaxDownloader.spec        # PyInstaller/Nuitka spec configuration
│   └── setup.sh                  # Linux/WSL dev setup script
├── Documentation/
│   ├── README.md                 # This file
│   ├── DEVELOPMENT_LOG.md        # Design decisions, architecture, and debugging history
│   ├── CONTRIBUTING.md           # Contribution guidelines
│   ├── implementation_plan.md    # Active engineering plans
│   └── walkthrough.md            # Feature walkthroughs
└── outputs/                      # Downloaded files (created at runtime)
    └── <PAN>-<Name>/
        └── AY_<year>/
            ├── <PAN>-26AS-_.pdf
            ├── <PAN>-26AS-_.txt
            ├── <PAN>-AIS-<FY>.pdf
            └── <PAN>-TIS-<FY>.pdf

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
3. Use the **Show Browser (Debug)** toggle if you wish to see the browser visibly working. Otherwise, it runs blazingly fast in the background (headless).
4. Check one or more clients from the list (or use **Select / Deselect All**)
5. Click **▶ Run** and choose:
   - **Download 26AS** — Form 26AS PDF + TXT (TRACES)
   - **Download / Request TIS & AIS** — AIS PDF + TIS PDF (Insight portal)
   - **Download Previously Requested AIS** — fetch a queued large AIS from Activity History
6. A **Batch Progress** popup shows live per-client status as the batch runs.
   Each row updates in real time through every step of the automation:

   | Status shown | What it means |
   |---|---|
   | `⏳ Logging in to ITD...` | Browser opening the ITD login page |
   | `⏳ Opening Compliance Portal…` | Clicking the AIS link to open Insight |
   | `⏳ Finding AIS menu…` | Locating the AIS nav link on the dashboard |
   | `⏳ Opening AIS portal…` | AIS portal tab opening |
   | `⏳ Loading AIS portal…` | Waiting for the Insight portal to finish loading |
   | `⏳ Selecting F.Y. <year>…` | Choosing the financial year on AIS home |
   | `⏳ Opening AIS download…` / `⏳ Opening TIS download…` | Opening the document download modal |
   | `⏳ Downloading AIS PDF…` | AIS PDF download in progress |
   | `⏳ Downloading TIS PDF…` | TIS PDF download in progress |
   | `✅ TIS downloaded` | TIS PDF saved |
   | `⏳ Downloading 26AS...` | 26AS (TRACES) download in progress |
   | `✅ AIS downloaded — fetching TIS...` | AIS saved, now fetching TIS |
   | `🕐 AIS queued — fetching TIS...` | AIS is large; queued server-side |
   | `⏳ Opening Activity History…` | Opening the queued-files list |
   | `⏳ AIS generating on ITD servers… (check N/19)` | Polling for a queued large AIS |
   | `⏳ AIS ready — downloading…` | Queued AIS is ready; fetching it |
   | `✅ AIS Downloaded instantly` / `✅ AIS Downloaded` / `✅ 26AS Downloaded` | Done |
   | `🕐 AIS request placed (Ref: …)` | Use *Download Previously Requested AIS* in ~5 min |
   | `⬜ No queued AIS for this FY — run Download / Request first` | Nothing was requested for that FY/client |
   | `🕐 AIS still generating — try again in a few minutes` | Queued AIS not ready after ~10 min |
   | `⬜ Skipped — AIS not available for this FY` | FY pre-dates AIS (before 2021-22) |
   | `❌ Failed — <reason>` | Error; reason shown inline and in the log panel |
   | `⏹ Stopped` | Aborted by the Stop button |

   > These ⏳ progress messages update live for every step so you always know
   > what the automation is doing in the background. Full step-by-step detail
   > (with URLs) is also written to the **Live Logs** panel.

   Use the **Stop** button to abort mid-batch. Use **Close** once finished.


Downloaded files are saved to:

```
<Output Directory>/<PAN>-<Client Name>/AY_<year>/
```

> The PDFs are automatically unlocked using the logic in `pdf_unlocker.py` and saved so they can be opened immediately without passwords.

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

For the full design history and root-cause analysis of the AIS download work,
see **[DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)**.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
