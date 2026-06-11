# FAQ — Frequently Asked Questions

---

## Installation and Setup

### Q: Do I need to install Python to use the Windows installer?

No. The Inno Setup `.exe` installer bundles everything — Python runtime, Playwright binaries, and all dependencies. Download and run the installer; no technical setup required.

If you are running from source (developers), Python 3.11+ and `pip install -r requirements.txt` are required.

---

### Q: Why does my antivirus flag the installer or the .exe?

AayDocCapio uses Nuitka to compile Python to native code. Some antivirus engines (Windows Defender, SmartScreen, Brave Shield) flag unsigned native executables from unknown publishers as suspicious — this is a false positive.

**What to do:**
1. **Windows Defender / SmartScreen:** Click "More info" → "Run anyway" when Windows shows the "Unknown publisher" warning.
2. **Brave/Chrome download block:** Click the download icon in the address bar → "Keep anyway".
3. If Defender quarantines the file, add an exclusion for the AayDocCapio install folder.

The app makes no outbound connections except to the official ITD portal (`eportal.incometax.gov.in`) and Insight portal (`ais.insight.gov.in`).

---

### Q: Does AIS/TIS download require Google Chrome?

Yes. The Insight Compliance Portal's Angular download handlers only work correctly with real Google Chrome (not Playwright's bundled Chromium). Install Chrome from https://www.google.com/chrome/ — no configuration needed; the app finds it automatically.

26AS downloads work fine with bundled Chromium; Chrome is only required for AIS/TIS.

---

### Q: The app crashes at startup with no error message. What do I do?

Check `startup_diag.log`, which is written before the main window opens:

- **Windows:** `%LOCALAPPDATA%\AayDocCapio\startup_diag.log`
- **Linux/macOS:** `~/.local/share/AayDocCapio/startup_diag.log`

This log captures exactly which step failed (imports, Qt init, etc.) and is the fastest way to diagnose a silent crash. Share it when reporting the issue.

---

## Credentials and Security

### Q: Where are client credentials stored?

All credentials are stored in `tax_vault.json`, a file on your local machine next to the app. Passwords are encrypted with AES-128 (Fernet, key derived via PBKDF2HMAC-SHA256). The file never leaves your machine — the app has no telemetry and no cloud sync.

**Important:** Keep `tax_vault.json` out of version control and shared folders.

---

### Q: What password protects the vault?

The current release uses a fixed application-level key (not a user-entered master password). The encryption protects against casual inspection of the file; it is not a substitute for OS-level disk encryption on a shared machine. A user-configurable master password is on the roadmap.

---

### Q: Can the app see my clients' tax data?

No. The app only automates the download and saves the files to your chosen folder. It does not parse, store, or transmit any tax data. The files are yours.

---

## Downloads

### Q: A client's download shows "❌ Failed — Invalid Password". What's wrong?

The portal password stored in the vault does not match the client's current ITD portal password. Open the client's record (••• → Edit) and update the password. Note: the portal password is different from the PAN/Aadhaar login — it's the password the client set on the e-Filing portal.

---

### Q: A client shows "AUTHENTICATION FAILED: 2FA enabled". What do I do?

The client's ITD account has Two-Step Authentication turned on. Automated login is not possible while 2FA is active.

**Resolution:** Ask the client to log into the ITD portal → Profile → My Profile → Login Settings → disable Two-Step Authentication. After disabling, the app will work normally.

---

### Q: The app shows "Already logged in" or the download gets stuck at login.

The client may have an active session open in another browser. Wait a few minutes for the session to expire, or ask the client to log out of the portal manually, then retry.

This is tracked as bug B-04 — automatic detection and dismissal of the "already logged in" prompt is planned.

---

### Q: AIS download shows "AIS too large — use AIS Utility". Can the app handle this?

Not automatically. When AIS data is too large, the ITD portal cannot generate the PDF and directs you to the AIS Utility desktop app. The app detects this condition and reports it clearly; the batch continues with other clients.

**Workaround:** Download the AIS JSON from the portal manually and open it in the AIS Utility app. Automated JSON download for large-file cases is tracked as enhancement F-08.

---

### Q: 26AS download shows "26AS too large for inline download".

For assessees with very large Form 26AS data, TRACES does not serve the file through the ITD portal. You must log directly into `tdscpc.gov.in` and place a download request there.

This is tracked as bug B-07. An automated TRACES-direct flow is planned for a future release.

---

### Q: PDF files are downloaded but still password-protected. How do I open them?

The app attempts to unlock PDFs automatically using standard ITD password combinations (PAN + DOB variants). If none match, the file is saved locked.

The standard passwords to try manually:
- AIS/TIS PDFs: `<PAN><DOB as DDMMYYYY>` (e.g. `AAAPT0001A01011980`)
- Sometimes lowercase PAN: `aaapt0001a01011980`

If the DOB stored in the vault is wrong, PDF unlock will always fail — verify the DOB first.

---

### Q: The 26AS TXT file is missing from the output folder.

The 26AS TXT is delivered inside a password-protected ZIP. The ZIP password is the client's DOB in `DDMMYYYY` format. If the DOB in the vault is incorrect, the ZIP cannot be extracted and the TXT is not saved.

Check the DOB in the client's vault record (••• → Edit) matches the ITD portal's registered DOB exactly.

---

### Q: All my AIS downloads show the same Financial Year (always 2025-26) regardless of what I select.

This was a known bug fixed in v1.1.0. The old "Download AIS/TIS" button on the Instructions tab had a portal-side bug that ignored the selected FY. The app now uses the correct download flow via the AIS Home tile icons.

Update to the latest version if you are on v1.0.x.

---

## Bulk Operations

### Q: I imported the same Excel file twice and now have duplicate clients.

This is bug B-05 — the upsert-by-PAN logic has a known failure mode. As a workaround:
1. Delete the duplicate records manually (••• → Delete for each duplicate).
2. Re-import once.

A fix is tracked in the issues backlog.

---

### Q: What's the recommended batch size?

There is no hard limit. The app applies a 5-second cooldown between clients to avoid triggering the ITD portal's rate-limit. For 50 clients downloading 26AS, expect approximately 90–120 minutes total runtime. Very large batches (100+) are best run overnight.

---

## Platform-Specific

### Q: The app shows a blank window on Linux/WSL (WSLg).

This is a WSLg compositor glitch, not an app bug. Fix:

```powershell
# In Windows PowerShell
wsl --shutdown
```

Then relaunch WSL and the app. Alternatively, force the X11 backend:

```bash
QT_QPA_PLATFORM=xcb python app.py
```

---

### Q: On macOS, the AY dropdown closes immediately when I click it.

This was fixed in v1.1.0. A 300ms debounce now prevents the dropdown from closing on the same click that opened it. Update to the latest version.

---

### Q: The output directory shows a Linux path on Windows after running in WSL.

Fixed in v1.4.0. The app now always resolves the output directory to the Windows-native Downloads path when `USERPROFILE` is set. If you stored a WSL path in the vault previously, reset the output directory in Settings.
