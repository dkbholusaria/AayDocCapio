# Product Requirements Document — AayDocCapio

**Version:** 1.6.4  
**Status:** Current  
**Last updated:** 2026-06-19

---

## 1. Overview

AayDocCapio is a standalone desktop utility for Indian Chartered Accountants and tax professionals who manage Income Tax filings for multiple clients. It automates the otherwise manual, repetitive work of logging into the ITD e-Filing portal for each client and downloading their tax documents — in bulk, in one run — converting AIS JSON files to formatted Excel, and emailing these documents directly to clients.

### Problem statement

A CA or tax practitioner managing 50–200+ clients must download Form 26AS, AIS, and TIS from the ITD portal every assessment year. Doing this manually takes 5–10 minutes per client — an entire working day for a large practice. The portal has no bulk-export feature. Existing tools are either cloud-based (raising credential-security concerns) or require technical setup beyond a typical office user.

### Solution

A local, encrypted desktop app that:
- Stores client credentials on-device (AES-128, never uploaded anywhere)
- Automates Chromium/Chrome to log in, navigate, and download as a real user would
- Presents results in a clear batch-progress view with per-client status

---

## 2. Users

| Persona | Description |
|---|---|
| **Primary — CA / Tax Professional** | Manages 20–200+ clients, non-technical, Windows-first, needs bulk speed and clear error messages |
| **Secondary — Sole Practitioner** | Manages a handful of clients, may run from macOS or Linux |
| **Developer / Contributor** | Runs from source on Linux/WSL, needs cross-platform dev setup |

---

## 3. Goals and Non-Goals

### Goals
- Reduce per-client download time from ~7 min manual to ~90 seconds automated
- Keep all credentials strictly on-device (no cloud, no telemetry)
- Work on Windows (primary), macOS, and Linux/WSL without code changes
- Fail gracefully per-client: one bad password never aborts the batch
- Produce a human-readable status report (Excel) at the end of each run

### Non-Goals
- Filing returns, uploading documents, or any write operation on the ITD portal
- Storing or transmitting files to any cloud service
- Supporting portals other than `eportal.incometax.gov.in` and `ais.insight.gov.in`
- Acting as a general-purpose browser automation framework

---

## 4. Feature Requirements

### 4.1 Client Vault

| ID | Requirement | Priority |
|---|---|---|
| V-01 | Store client records (Name, PAN, DOB, portal password) in a local encrypted JSON file | Must |
| V-02 | Encrypt passwords with AES-128 Fernet; key derived via PBKDF2HMAC-SHA256 | Must |
| V-03 | Add, edit, delete clients via GUI form (popup dialog) | Must |
| V-04 | Bulk import from Excel (.xlsx) or CSV (.csv) with columns: Name, PAN, DOB, Password | Must |
| V-05 | Validate PAN format (10-char: `[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z]`) at save time | Must |
| V-06 | Validate DOB (DD-MM-YYYY, real calendar date, not future, not before 1900) | Must |
| V-07 | Accept multiple DOB input formats in bulk import (DD/MM/YYYY, ISO, Excel date serial) | Must |
| V-08 | Export vault data to Excel / CSV | Should |
| V-09 | Generate a blank import template | Should |

### 4.2 Document Downloads

| ID | Requirement | Priority |
|---|---|---|
| D-01 | Download Form 26AS (PDF + TXT) via TRACES portal | Must |
| D-02 | Download AIS PDF via Insight Compliance Portal | Must |
| D-03 | Download TIS PDF via Insight Compliance Portal | Must |
| D-04 | Request AIS generation if not immediately available (queue mode) | Should |
| D-05 | Download previously queued AIS once ready | Should |
| D-06 | Automatically unlock downloaded PDFs using PAN+DOB derived password | Must |
| D-07 | Automatically extract 26AS TXT from password-protected ZIP | Must |
| D-08 | Save files as `<OUTPUT_DIR>/<PAN>-<Name>/AY_<year>/` | Must |
| D-09 | Name files: `<PAN>-26AS-<AY>.txt`, `<PAN>-AIS-<FY>.pdf`, `<PAN>-TIS-<FY>.pdf` | Must |
| D-10 | Detect "AIS too large for PDF" and fail fast with instructions to use AIS Utility | Must |
| D-11 | Detect "26AS too large for inline download" and fail fast with TRACES-direct instructions | Must |

### 4.3 Assessment Year Management

| ID | Requirement | Priority |
|---|---|---|
| A-01 | Maintain list of AY/TY/FY entries in `assessment_years.json` | Must |
| A-02 | Allow user to toggle years on/off and add custom entries via Settings dialog | Should |
| A-03 | Show the correct label prefix (AY / TY / FY) based on entry type in all UI and filenames | Must |

### 4.4 Batch Execution

| ID | Requirement | Priority |
|---|---|---|
| B-01 | Run downloads for all selected clients sequentially in a background thread | Must |
| B-02 | Show live per-client status in a Batch Progress dialog | Must |
| B-03 | Isolate each client in its own browser context (no session bleed) | Must |
| B-04 | Apply 5-second cooldown between clients to avoid ITD rate-limiting | Must |
| B-05 | Allow Stop at any point; stop cancels the active browser task immediately | Must |
| B-06 | Allow Resume after Stop (retry only incomplete clients) | Should |
| B-07 | Record last download status and path per client per AY in vault | Must |
| B-08 | Export batch results to Excel (.xlsx) with per-row timestamps | Should |

### 4.5 Error Handling

| ID | Requirement | Priority |
|---|---|---|
| E-01 | Detect invalid password: fail fast with portal error text, do not retry | Must |
| E-02 | Detect 2FA/OTP accounts: fail fast with actionable message (disable 2FA instructions) | Must |
| E-03 | Detect "already logged in" portal prompt: dismiss and continue | Should |
| E-04 | Translate network error codes (ERR_EMPTY_RESPONSE etc.) to plain English | Must |
| E-05 | Show startup diagnostics log before Qt initialises (for crash diagnosis) | Must |
| E-06 | Detect missing VC++ Redistributable at install time (Windows) | Must |

### 4.6 UI and Settings

| ID | Requirement | Priority |
|---|---|---|
| U-01 | Light and Dark Navy themes; persist preference across sessions | Should |
| U-02 | Full-width client table with Name, PAN, DOB, Last Download Status, Last Saved Location | Must |
| U-03 | Sortable Name and PAN columns | Should |
| U-04 | Searchable client list (live filter) | Should |
| U-05 | Headless browser mode by default; visible mode toggle for CAPTCHA handling | Must |
| U-06 | Output directory picker with platform-correct default (Downloads folder) | Must |
| U-07 | Corporate proxy auto-detection from Windows registry | Should |

### 4.7 Email Delivery

| ID | Requirement | Priority |
|---|---|---|
| M-01 | Mail downloaded tax documents (26AS, AIS, TIS) directly to clients | Must |
| M-02 | Rich text email composer with placeholder chips (e.g. `{client_name}`, `{pan}`) | Must |
| M-03 | Bulk sending with live progress table and detailed logs | Must |
| M-04 | Pre-configured SMTP settings for Gmail, Outlook, Microsoft 365, Yahoo, iCloud | Should |

### 4.8 AIS JSON → Excel Conversion

| ID | Requirement | Priority |
|---|---|---|
| X-01 | Decrypt and convert AIS JSON to structured Excel workbooks | Must |
| X-02 | Per-category sheets with proper Indian numbering formats and deductor subtotals | Must |
| X-03 | Consolidated capital market sheet (aggregating SFT-17/18) with STCG/LTCG formulas | Must |
| X-04 | Grandfathering calculations under Section 55(2)(ac) for pre-2018 assets | Must |

### 4.9 Interactive User Manual & UI Navigation

| ID | Requirement | Priority |
|---|---|---|
| N-01 | Integrated 13-section offline HTML User Manual with embedded app screenshots | Must |
| N-02 | Left-side sticky navigator panel with 37 nested sub-sections and JS Scrollspy tracking | Should |
| N-03 | Clean top sticky navbar containing logo, branding, and external 'Contact us' link | Should |
| N-04 | Last Download Time column in the client grid to display successful run history | Must |
| N-05 | Rebranding of Client Vault to Managing Clients and grouping bulk import/export under it | Must |
| N-06 | Step-by-step procedures for bulk 26AS/AIS downloads and specific menu options to click | Must |
| N-07 | Comprehensive SMTP Email Setup guidelines with provider presets and Google App Passwords | Must |
| N-08 | Detailed inbuilt check for updates and auto-updater guidelines | Should |

---

## 5. Security Requirements

| ID | Requirement |
|---|---|
| S-01 | PAN must never appear in log output, error dialogs, or exception strings (mask as `PAN[:3]XXXXXXX`) |
| S-02 | `tax_vault.json` must never be committed to version control |
| S-03 | No outbound network connections except to official ITD portal domains |
| S-04 | Credentials submitted only to `eportal.incometax.gov.in`; never to any third party |

---

## 6. Platform Requirements

| Platform | Support level |
|---|---|
| Windows 10/11 (x64) | **Primary** — standalone installer (Nuitka + Inno Setup / WiX) |
| macOS 13+ (Apple Silicon + Intel) | **Supported** — run from source or Nuitka app bundle |
| Linux / WSL2 | **Supported** — run from source |

- Python 3.11+
- Google Chrome installed (required for AIS/TIS; bundled Chromium suffices for 26AS)

---

## 7. Out-of-Scope for v1.x

- AIS JSON download (CAPTCHA-gated for most accounts; large-file JSON is a future enhancement — see F-08 in backlog)
- TRACES-direct login flow for large 26AS files (tracked as B-07)
- Multi-user / multi-vault support
- Scheduling / unattended automation
