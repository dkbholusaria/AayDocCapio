# Implementation Plan - Standalone GUI Tax Downloader

The goal is to build a standalone, GUI-based desktop application (`/home/deepak/projects/tax-downloader`) for Windows and Linux. The application automates the sequential login, download of Form 26AS, AIS, and TIS, and logout from the Indian Income Tax Department (ITD) e-Filing portal for multiple clients.

The GUI will be constructed using `customtkinter` (matching the modern design language and components of `KarOrbis`) and packaged for Windows distribution.

## User Review Required

> [!IMPORTANT]
> **Data Security**: All assessee credentials (NAME, PAN, DOB, and ITD Password) will be stored in a dedicated encrypted local file `tax_vault.json` using PBKDF2HMAC + Fernet AES-128. The decryption/encryption key is derived from a configurable master password.
>
> **Packaging for Windows**: Since the development is on Linux/WSL, we will provide a `build_win.bat` script and a `setup.py`/`pyinstaller` configuration. This will enable packaging the entire application into a single-file standalone Windows executable (`TaxDownloader.exe`) with all dependencies (including Chromium/Playwright binaries) bundled or setup on first run.

## Open Questions

> [!NOTE]
> 1. **Bulk Upload Format**: We propose supporting both Excel (`.xlsx`) and CSV (`.csv`) formats for bulk import. The columns required will be: `Name`, `PAN`, `DOB` (DD-MM-YYYY), and `Password`. Does this work?Yes
> 2. **Playwright Integration on Windows**: Playwright requires browser binaries to run. In a standalone `.exe` distribution, we can package them, or write code that checks for and installs Chromium on first-run. We propose a first-run downloader built into the UI (self-healing) so the executable stays lightweight (~20MB vs ~150MB). Which approach do you prefer?
> 3. **AIS/TIS Formats**: We will download AIS in both PDF and JSON formats, and TIS in PDF format by default.

## Proposed Architecture

```text
/home/deepak/projects/tax-downloader/
├── requirements.txt         # GUI, Cryptography, and Scraping dependencies
├── app.py                   # Main entry point for the CustomTkinter GUI app
├── vault.py                 # Encrypted JSON database manager (manually + bulk CRUD operations)
├── build_win.bat            # Windows batch script to compile executable using PyInstaller
├── automation/
│   ├── __init__.py
│   ├── browser.py           # Self-healing Playwright browser manager
│   ├── auth.py              # ITD Login and logout automation
│   ├── downloader.py        # Redirection, 26AS, and AIS/TIS download logic
└── outputs/                 # Subfolders named "PAN-Name of the assessee" (e.g. "AAAPT0001A-John Doe")
```

## Proposed Changes

### GUI Application Framework

#### [NEW] [requirements.txt](file:///home/deepak/projects/tax-downloader/requirements.txt)
Includes `customtkinter`, `Pillow`, `pandas`, `openpyxl`, `playwright`, `cryptography`, and `pyinstaller`.

#### [NEW] [vault.py](file:///home/deepak/projects/tax-downloader/vault.py)
Encrypted JSON vault manager. Provides:
- Initialization of `tax_vault.json`.
- Encryption and decryption of passwords.
- CRUD operations for assessees (add manually, edit, delete).
- Bulk import function from Excel/CSV (validating fields: PAN, DOB, etc.).
- Bulk export / template generation function.

#### [NEW] [automation/browser.py](file:///home/deepak/projects/tax-downloader/automation/browser.py)
Playwright browser manager:
- Handles initializing Chromium.
- Installs Chromium automatically (via CLI process or UI status update) if binaries are missing on the target computer.

#### [NEW] [automation/auth.py](file:///home/deepak/projects/tax-downloader/automation/auth.py)
ITD Login & Logout:
- Automates login steps: user ID, SAM check, password filling, and dashboard settlement.
- Automates session logout by clicking the top-right profile and selecting Log Out to ensure clean handoff for subsequent accounts.

#### [NEW] [automation/downloader.py](file:///home/deepak/projects/tax-downloader/automation/downloader.py)
Document download manager:
- For Form 26AS: handles TRACES redirect, agreement acceptance, AY selection, and PDF export.
- For AIS/TIS: handles Compliance Portal redirect, alert dismissal, AY selection, and AIS/TIS file downloads.
- Saves documents to `<ROOT>/<PAN>-<NAME>/AY_<AY>/`.

#### [NEW] [app.py](file:///home/deepak/projects/tax-downloader/app.py)
Stunning CustomTkinter Dashboard containing:
- **Title Strip & Header**: Premium branding with dark theme styling.
- **Assessee List / Table**: Displays saved assessees with check boxes for selective downloads.
- **Form Panel (Left/Sidebar)**: Fields to manually add/edit an assessee (Name, PAN, DOB, Password). Buttons for: Add, Edit, Delete, Import CSV/Excel, and Export/Template.
- **Settings Panel**: Target Download Root Directory selector (using file dialog picker) and Assessment Year dropdown.
- **Control Section**: "Select All" checkbox, "Start Bulk Download" button.
- **Progress Panel**: Visual status updates, status bar, and real-time logs (re-directing stdout/logger output to a text box).

## Verification Plan

### Automated/Local Testing
1. Launch the UI:
   ```bash
   python app.py
   ```
2. Test manual CRUD: add, edit, and delete dummy assessees.
3. Test bulk import: load dummy `.xlsx` or `.csv`.
4. Run automation download for a selected assessee to verify login, download, save to `PAN-Name` folders, and logout.

### Manual Windows Verification
- Package the application:
  ```bash
  pyinstaller --noconsole --onefile app.py
  ```
- Run the compiled executable on a Windows machine to verify UI, database persistence, and Playwright execution.
