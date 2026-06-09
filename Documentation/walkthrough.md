# Walkthrough - Standalone GUI Tax Downloader

> ⚠️ **HISTORICAL — describes the original prototype.** This walkthrough reflects
> the first CustomTkinter/pandas/PyInstaller version. The current app uses
> **PyQt6**, **openpyxl** (no pandas), **Nuitka** builds, real **Google Chrome**,
> and a **Run dropdown** (no document checkboxes). AIS JSON is no longer
> downloaded (CAPTCHA-gated). For the accurate, up-to-date picture see
> **[README.md](README.md)** and **[DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)**.

We have created the standalone GUI Tax Downloader application in `/home/deepak/projects/AayDocCapio`. The application allows a user to manage client/assessee credentials securely and download **Form 26AS**, **AIS**, and **TIS** from the Indian Income Tax Department (ITD) e-Filing portal sequentially.

## Changes Made

We initialized the standalone project and created the following components:

1. **[requirements.txt](file:///home/deepak/projects/AayDocCapio/requirements.txt)**
   Defines all required dependencies (customtkinter, Pillow, pandas, openpyxl, playwright, cryptography, and pyinstaller).

2. **[vault.py](file:///home/deepak/projects/AayDocCapio/vault.py)**
   The local database manager:
   - Initialized `tax_vault.json` for credential persistence.
   - Encrypts and decrypts password records using PBKDF2HMAC + Fernet AES-128 derivation.
   - Implements full CRUD methods (add, edit, delete).
   - Handles bulk importing from Excel (`.xlsx`) or CSV (`.csv`) and generates standard templates.

3. **[automation/browser.py](file:///home/deepak/projects/AayDocCapio/automation/browser.py)**
   Playwright Chromium manager:
   - Manages browser contexts.
   - Includes an auto-provisioner/self-healing routine that runs `playwright install chromium` if binaries are missing.

4. **[automation/auth.py](file:///home/deepak/projects/AayDocCapio/automation/auth.py)**
   ITD Login & Logout flow:
   - Automates the 2-step ITD credentials injection and Secure Access Message (SAM) confirmation.
   - Handles the top-right profile menu to perform clean browser logouts for sequential client runs.

5. **[automation/downloader.py](file:///home/deepak/projects/AayDocCapio/automation/downloader.py)**
   Document extraction routines:
   - Navigates through e-File menus using zero-scroll mouseovers and clicks to prevent page reflow issues.
   - For **26AS**: redirects to TRACES, accepts popups, selects the Assessment Year, selects "HTML" format, and downloads the exported PDF.
   - For **AIS/TIS**: redirects to the Compliance Portal, dismisses alerts, selects the Assessment Year, and downloads TIS PDF, AIS PDF, and AIS JSON documents.
   - Places downloads in the structure: `<ROOT_FOLDER>/<PAN>-<Name>/AY_<Year>/`.

6. **[app.py](file:///home/deepak/projects/AayDocCapio/app.py)**
   The core CustomTkinter dashboard:
   - **Form Frame (Left)**: Simple, styled panel to manage profiles, template generation, and bulk imports.
   - **Dashboard Panel (Right)**: Settings bar (AY select, checkable documents, output path browser) and a scrollable table displaying clients with checkable list items.
   - **Console Frame (Bottom)**: Real-time terminal simulator showing engine logs during execution.
   - **Thread Safety**: Offloads all Playwright and scraper logic to a background worker daemon to keep the GUI responsive.

7. **[build_win.bat](file:///home/deepak/projects/AayDocCapio/build_win.bat)**
   Windows batch file to compile the CustomTkinter project into a single-file executable using PyInstaller.

---

## How to Run

### Local Run (Linux/WSL/Windows development)
If dependencies are installed in your active environment:
```bash
python3 app.py
```

Or run via the virtual environment folder:
```bash
/home/deepak/projects/KarOrbis/.venv/bin/python app.py
```

### Packaging for Windows Standalone Executable
On a Windows system:
1. Double-click or execute **`build_win.bat`** from a command prompt inside the project folder.
2. The batch script will automatically check for Python, verify dependencies from `requirements.txt`, install `pyinstaller`, and compile the application.
3. The standalone executable will be saved in `dist/AayDocCapio/AayDocCapio.exe`.

---

## Verification Results

- Verified all Python source files compiles without syntax or import errors.
- Verified database and encryption logic using a unit test script: successfully created test vault, encrypted credentials, decrypted, verified CRUD, and cleaned up.
