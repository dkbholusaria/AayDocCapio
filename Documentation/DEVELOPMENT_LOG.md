# Development Log — ITD Docs Downloader

This document records the major design decisions, the problems encountered while
automating the Income Tax Department (ITD) e-Filing and Insight/AIS portals, and
the root-cause fixes that finally made AIS/TIS downloads reliable. It is meant as
a reference so the hard-won knowledge is not lost or re-learned.

---

## 1. Goal

A standalone desktop utility (PyQt6 + Playwright) that logs into the ITD
e-Filing portal and bulk-downloads, for many clients in one run:

- **Form 26AS** (via the TRACES portal)
- **AIS** — Annual Information Statement (PDF) via the Insight Compliance Portal
- **TIS** — Taxpayer Information Summary (PDF) via the same portal

Credentials (PAN, DOB, portal password) are stored in a local encrypted vault.

---

## 2. Architecture

app.py                       PyQt6 GUI, batch orchestration, progress dialog
vault.py                     Encrypted credential vault (openpyxl + csv, no pandas)
automation/
  browser.py                 Playwright browser manager (launches real Chrome)
  auth.py                    ITD login / logout
  downloader_26as.py         Form 26AS (TRACES) flow
  downloader_ais_tis.py      AIS / TIS (Insight portal) flow
  downloader.py              Shared helpers (status badge, step logger)

The GUI runs the batch in a background thread; per-client status is pushed to a
live **Batch Progress** dialog via Qt signals. Each client is processed in its
own `try/except`, so one client's failure never aborts the batch.

---

## 3. Key Design Decisions

### 3.1 Run dropdown (replaced three buttons)

The action bar uses a single **▶ Run** split-button (`QToolButton` + `QMenu`):

- Download 26AS
- Download / Request TIS & AIS
- Download Previously Requested AIS

The old per-document checkboxes ("26AS / AIS / TIS" tick boxes) were removed as
redundant — the menu choice itself expresses intent. AIS and TIS always download
together when "Download / Request TIS & AIS" is chosen.

### 3.2 Stop button lives on the progress popup

The Stop control was moved from the main toolbar into the Batch Progress dialog
footer. It calls `stop_automation()` on the main window, then hides itself when
the batch finishes (Close button takes over).

### 3.3 Live per-client progress dialog

`BatchProgressDialog` shows one row per assessee (Name | Status). Status updates
arrive from the worker thread via `pyqtSignal`. It is **window-modal**
(`Qt.WindowModality.WindowModal`) and uses `Qt.WindowType.Dialog` so it blocks
the parent window and renders an active title bar, while `show()` (not `exec()`)
keeps the event loop alive for live updates.

### 3.4 Vault without pandas

Import/export/template use `openpyxl` + `csv` directly (pandas was removed to cut
binary size). `import_bulk()` returns `(added, updated, errors)`.

---

## 4. The Long Debugging Saga — AIS/TIS Downloads

For a long time AIS/TIS "succeeded" in logs but **no file ever downloaded** and
nothing appeared in the portal's Activity History. Many click strategies were
tried and all appeared to fail:

- plain Playwright `.click()`
- `element.click()` via `page.evaluate`
- `dispatch_event("click")`
- raw `page.mouse.click(x, y)` at `bounding_box()` coordinates
- `getBoundingClientRect()` viewport coordinates
- keyboard `focus()` + `Enter`
- `Zone.current.run(() => btn.click())` (Angular NgZone)
- ARIA `get_by_role("button", name="Download")`

### 4.1 Root cause #1 — `expect_download` on the wrong object (THE bug)

```python
# WRONG — raised "'BrowserContext' object has no attribute 'expect_download'"
async with portal.context.expect_download(...) as dl_info:
    ...
# CORRECT
async with portal.expect_download(...) as dl_info:
    ...
```

`expect_download` exists only on **Page**, never on **BrowserContext**. The wrong
call raised an `AttributeError` *before the click result could be captured*. A
bare `except` swallowed it and the code fell through to "queued / Reference ID:
N/A". **The download was never actually attempted.** This single mistake masked
every click strategy above — none of them ever had a chance.

Fixed in all 7 call sites across `downloader_ais_tis.py` and `downloader.py`.
Once fixed, AIS downloaded **instantly for every year tested** (2025-26, 2023-24),
so the elaborate "Request → wait → Activity History" two-phase flow is rarely
needed in practice.

### 4.2 Root cause #2 — must use real Google Chrome

The Insight/AIS portal's Angular handlers/downloads behave correctly only on the
user's installed Google Chrome, not Playwright's bundled Chromium.

```python
# browser.py — prefer real Chrome, fall back to bundled Chromium
await self._playwright.chromium.launch(headless=headless, channel="chrome", ...)
```

This was confirmed against a competitor app (Node/Electron) whose own log proved
AIS only downloaded **after** `npx playwright install chrome` installed real
Chrome. If Chrome is absent we fall back to bundled Chromium and warn the user:
26AS works, but AIS/TIS downloads need Chrome.

### 4.3 Root cause #3 — viewport / window sizing

`--start-maximized` **conflicts** with a fixed Playwright viewport and distorts
the aspect ratio, collapsing the ITD nav and pushing it off-screen. Fix:

```python
# browser.py context
viewport={"width": 1600, "height": 900}   # no --start-maximized, no bypass_csp
```

Even at 1600px the dashboard nav can collapse into a hamburger, so before
clicking `a#AIS` (or `e-File` for 26AS) we:

1. `window.scrollTo(0,0)` + reset every scrollable container (nav can be scrolled
   out of view),
2. click `#hamburgerOpen` (with fallback selectors) if present.

---

## 5. ITD / Insight Portal Flow (verified against live HTML)

### 5.1 Login (`auth.py`)

1. Navigate to `#/login`, wait for Angular hydration.
2. Fill `#panAdhaarUserId`, click **Continue**.
3. Wait for SAM (Secure Access Message) checkbox `#passwordCheckBox-input`, tick it.
4. Click **Continue**, then select the **Password** radio
   (`//label[text()='Password']`).
5. Fill `#loginPasswordField`, click **Continue** (up to 4 attempts).
6. Handle `#loginMaxAttemptsPopup` → "Login Here".
7. Detect wrong password from inline error text (portal says
   *"Error : Invalid Password, Please retry."*) and **fail fast** with that
   message rather than retrying.
8. Dashboard success = URL no longer contains `/login`.
9. On any failure the login page is closed (no orphan-tab leaks across clients).

### 5.2 Opening the AIS portal (`_open_ais_portal`)

- Open hamburger, click `a#AIS`.
- Arm a new-tab listener **before** the click; dismiss an optional "Yes"
  confirmation; race between a new tab opening and the same tab navigating to
  `ais.insight.gov.in`.

### 5.3 AIS portal navigation

- Portal lands on `/complianceportal/ais/instructions`.
- FY selection: go to `/ais/home` via the sub-navbar AIS tab, open
  `.fy-dropdown button#dropdownMenuButton`, pick `F.Y. YYYY-YY`
  (`button.dropdown-item`), return to the **Instructions** tab.
- The instructions page has a **`Download AIS/TIS (F.Y. ...)`** shortcut button
  that opens the download modal — this is the reliable entry point.

### 5.4 Download modal (`mat-dialog-container`)

- AIS modal rows (each `div.d-flex` with `p.dialog-sub-head` + one
  `button.dialog-outline-btn`):
  - "Annual Information Statement (AIS) - PDF" ← downloaded
  - "Annual Information Statement (AIS) - JSON (for AIS Utility)" ← skipped (CAPTCHA)
  - "AIS Consolidated Feedback (ACF) - PDF" ← skipped
- TIS is a **separate** modal/row: "Taxpayer Information Summary (TIS) - PDF".
- `request_ais()` downloads AIS PDF, then `download_tis()` downloads TIS PDF in
  the same portal session.
- Files saved as `<PAN>-AIS-<FY>.pdf` and `<PAN>-TIS-<FY>.pdf`.

### 5.5 Activity History (two-phase fallback, rarely needed)

For genuinely large files that queue instead of downloading instantly:

- Row = `tr.example-element-row`; columns by class
  (`mat-column-activityType`, `mat-column-description`, `mat-column-referenceId`,
  `mat-column-download`).
- Pending state: `img[alt="Progress"]` (`title="File in progress"`).
- Ready state: `a[title="Download file"]` → click to download.
- Poll every 30s up to 10 min.

---

## 6. Step Logging

`make_step_logger(log_callback, prefix)` in `downloader.py` returns a
`step(msg, page=None)` that emits numbered, URL-tagged progress lines, e.g.:

[AIS-OPEN] (6) Clicking a#AIS  |  url: https://eportal.incometax.gov.in/...
[AIS-DL]   (5) Download saved: AEKPB0205L-AIS-2025_26.pdf

Comprehensive step logs are deliberately **kept permanently** across login, 26AS,
and AIS/TIS — they make any future portal change trivially diagnosable.

---

## 7. Error Handling & Mixed Batches

- Each client runs in its own `try/except` — failures are isolated.
- A failed client records `_ais_results[pan] = "failed"` and the error string in
  `_last_errors[pan]`; the progress row shows `❌ Failed — <reason>` and the
  results dialog lists the distinct reasons.
- Example mixed batch (one wrong password, one correct): the wrong one fails fast
  with the portal's message and its tab is closed; the correct one downloads
  normally; the summary dialog reports both.

---

## 8. Security Constraints (must preserve)

- **PAN is never logged or shown in error messages** — always masked as
  `pan[:3] + "XXXXXXX"`.
- Credentials stored locally, AES-128 (Fernet), PBKDF2HMAC-SHA256.
- Credentials only ever submitted to the official ITD portal.

---

## 9. Environment Notes

- **WSLg blank window / `WARN:COPY MODE`**: a WSLg compositor glitch, not a code
  bug. Fix with `wsl --shutdown` (Windows PowerShell) and relaunch, or force the
  X11 backend (`QT_QPA_PLATFORM=xcb`). Not caused by the app.
- Build uses **Nuitka** (compiles to native code) + Inno Setup, not PyInstaller.

---

## 10. Status (as of 2026-06-04)

Working end to end:

- Login with robust error handling and fast-fail on bad password
- 26AS download (TRACES)
- AIS + TIS download for all years (instant)
- FY switching
- Mixed batches with per-client isolation and clear error reporting
- Permanent step logging

Pending / optional:

- Large-file queued path (Activity History) — implemented but seldom exercised
  since files download instantly
- PDF password removal (deferred)
- Windows build verification with all latest changes
