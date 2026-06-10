# Changelog

All notable changes to AayDocCapio are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.1.0] — 2026-06-10

### New Features

- **Batch Progress dialog — complete overhaul**
  - Columns: Name · PAN (monospace) · Status · Save Path
  - Save Path is a clickable hyperlink — opens the client's folder directly
  - Green progress bar with white text replaces the plain counter
  - Saving-to location shown in the footer next to the Open Folder button
  - Dialog is resizable and has a Maximize button
  - Window title reflects the active operation (e.g. "Downloading 26AS — Batch Progress")
  - AY/TY/FY prefix is correct per operation: 26AS shows AY or TY (from user's configuration), AIS/TIS shows FY

- **Resume after Stop**
  - Clicking Stop now shows a green ▶ Resume button
  - Resume retries only the clients that were stopped; already-completed clients are preserved
  - Same dialog stays open — no need to re-select year or clients

- **Download Report (Excel)**
  - "⬇ Download Report" button enabled when batch finishes
  - Exports an `.xlsx` with: Client Name · Save Folder (clickable hyperlink) · Status · Timestamp
  - Opens automatically after saving

- **Open Folder buttons**
  - "📂 Open Folder" in the footer opens the root download directory
  - Previously available per-client folder button replaced with cleaner hyperlink

- **macOS support** (merged from Dhruv's fork)
  - Platform-aware fonts: Avenir Next / Menlo on macOS vs Segoe UI / Cascadia Code on Windows
  - Light colour scheme forced on macOS to prevent dark-mode UI issues
  - AY/TY dropdown debounce fix (300ms) — prevents popup closing immediately on macOS

- **2FA / OTP detection**
  - If a client has 2FA enabled on the ITD portal, the app now detects it immediately (within seconds) instead of waiting 3 minutes for a timeout
  - Clear message: "AUTHENTICATION FAILED: This account has 2FA enabled..."

- **AIS "data too large" detection**
  - Portal error "Unable to generate PDF as data is too large" is now detected and reported clearly
  - Client is marked failed with instructions to use the AIS Utility app; batch continues

- **Antivirus false positive guidance**
  - Red warning banner on the download page with a popup modal covering Brave/Chrome, Windows Defender, and SmartScreen
  - Instructions added to README

### Improvements

- **Immediate Stop/Abort** — clicking Stop now cancels the browser task instantly via asyncio task cancellation instead of waiting for the current step to time out
- **Friendly error messages** — technical Playwright/network error codes (ERR_EMPTY_RESPONSE, ERR_ABORTED, ERR_CONNECTION_RESET etc.) are translated to plain English in the status column; full technical detail still in the log panel
- **Default download folder** — correctly resolves to `C:\Users\<name>\Downloads` on native Windows and WSL; falls back to Documents if Downloads doesn't exist
- **Saved path validation on startup** — if the stored download path is invalid on the current platform (e.g. a Linux path stored from WSL), it auto-resets to the correct platform default
- **Assessment Year in progress dialog** — shown as "AY 2026-27", "TY 2026-27", or "FY 2024-25" depending on operation and how the year was configured
- **AIS queued message** corrected to reference the actual menu item ("▶ Run → ⬇ Download Previously Requested AIS")
- **AIS Request Complete dialog** no longer appears when the batch was aborted by the user
- **Stopped rows sweep** — when Stop is clicked, all pending/in-progress rows are immediately marked ⏹ Stopped (previously they stayed as Waiting/Downloading)
- **Startup diagnostics** — `startup_diag.log` written before Qt initialises to help diagnose crashes on user machines
- **System proxy support** — automatically detects and applies Windows system proxy settings for Playwright
- **Doubled page load and element timeouts** for slow networks and proxy environments

### Bug Fixes

- Fixed AY/TY dropdown closing immediately on click on macOS (300ms debounce)
- Fixed `FileNotFoundError` when clicking Open Folder if the path is a WSL Linux path on Windows
- Fixed spurious "Future exception was never retrieved" console noise when Stop is clicked mid-navigation
- Fixed `D:\home\deepak\Downloads` path appearing on Windows when app was configured in WSL

### Documentation

- `Documentation/README.md` updated with installation, 2FA limitations, antivirus guidance
- `Documentation/DEVELOPMENT_LOG.md` updated through section 14
- GitHub Pages (`docs/index.html`) updated with antivirus modal

---

## [1.0.0] — 2026-05-15

Initial public release.

- Bulk download of Form 26AS (PDF + TXT) for multiple clients
- AIS / TIS download via ITD e-Filing portal automation
- Request AIS generation and download once ready
- Client vault with encrypted credentials (AES-256)
- Bulk import from Excel / CSV template
- Assessment Year management
- Headless and visible browser modes
- Windows installer (Inno Setup) with Chromium auto-install
