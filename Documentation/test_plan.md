# Test Plan

**Version:** 1.2.0  
**Last updated:** 2026-06-11

This document describes the manual test cases for AayDocCapio. There is currently no automated test suite; all verification is manual. Test cases are grouped by module.

---

## Test environment

| Item | Requirement |
|---|---|
| OS | Windows 10/11 (primary), macOS 13+, or Linux/WSL2 |
| Python | 3.11+ with `.venv` activated |
| Google Chrome | Installed (required for AIS/TIS test cases) |
| Live ITD credentials | At least one valid PAN/DOB/password for portal tests |
| Test import file | `testdata/` — sample 26AS files; prepare a valid client `.xlsx` for import tests |

Run the app from source for all tests:
```bash
python app.py
```

---

## TC-01 — Vault: Add single client

**Precondition:** App is open, vault is empty or has existing clients.

| Step | Action | Expected result |
|---|---|---|
| 1 | Client Master → Add Single Client | Popup dialog opens |
| 2 | Enter Name: `Test User`, PAN: `AAAPT0001A`, DOB: `01-01-1980`, Password: `testpass` | Fields accept input |
| 3 | Click Save | Dialog closes; new client appears in table |
| 4 | Relaunch app | Client is still present (persisted in vault) |

---

## TC-02 — Vault: PAN validation

| Step | Action | Expected result |
|---|---|---|
| 1 | Client Master → Add Single Client | Dialog opens |
| 2 | Enter PAN: `INVALIDPAN` | — |
| 3 | Click Save | Inline error: "Invalid PAN format" with format explanation |
| 4 | Enter PAN: `aaapt0001a` (lowercase) | — |
| 5 | Click Save | Accepted (auto-uppercased) OR inline error — PAN saved as `AAAPT0001A` |

---

## TC-03 — Vault: DOB validation

| Step | Action | Expected result |
|---|---|---|
| 1 | Open Add client dialog | — |
| 2 | DOB: `32-01-1980` | Save → error: not a valid date |
| 3 | DOB: `01-01-2030` | Save → error: cannot be a future date |
| 4 | DOB: `01-01-1980` | Save → accepted |

---

## TC-04 — Vault: Edit client

| Step | Action | Expected result |
|---|---|---|
| 1 | Click ••• on any client row | Context menu: Edit / Delete |
| 2 | Click Edit | Dialog pre-filled with client's current values |
| 3 | Change Name; click Save | Table updates; vault persists change after relaunch |

---

## TC-05 — Vault: Delete client

| Step | Action | Expected result |
|---|---|---|
| 1 | Click ••• → Delete on a client row | Confirmation prompt |
| 2 | Confirm | Client removed from table and vault |

---

## TC-06 — Bulk import: valid file

**Precondition:** Prepare `test_import.xlsx` with columns Name, PAN, DOB, Password and 3 valid rows.

| Step | Action | Expected result |
|---|---|---|
| 1 | Client Master → Import Excel/CSV → select `test_import.xlsx` | — |
| 2 | Confirm | "3 added, 0 updated, 0 errors" dialog; all 3 appear in table |
| 3 | Import same file again | "0 added, 3 updated, 0 errors" (upsert by PAN) |

---

## TC-07 — Bulk import: invalid rows

| Step | Action | Expected result |
|---|---|---|
| 1 | Import a file with one row having an invalid PAN | Import completes; result shows "1 error: Row 2: Invalid PAN..." |
| 2 | Import a file missing the `Password` column header | Import fails with "Missing required columns: password" |

---

## TC-08 — Assessment Year dropdown

| Step | Action | Expected result |
|---|---|---|
| 1 | Open AY dropdown in the settings bar | Dropdown opens and stays open |
| 2 | Click a different AY | Dropdown closes; selected AY label updates |
| 3 | Settings → Manage Years → deactivate one year | That year no longer appears in the dropdown |

---

## TC-09 — 26AS download (live test)

**Precondition:** At least one client with valid credentials; valid AY selected; output directory set.

| Step | Action | Expected result |
|---|---|---|
| 1 | Select one client; Run → Download 26AS | Batch Progress dialog opens |
| 2 | Observe progress | Status cycles: Waiting → Logging in → Downloading 26AS → ✅ 26AS Downloaded |
| 3 | Open output folder | `<PAN>-<Name>/AY_<year>/` contains `<PAN>-26AS-<AY>.txt` (and optionally `.pdf`) |
| 4 | File is unlocked | TXT file opens without a password prompt |

---

## TC-10 — AIS + TIS download (live test)

**Precondition:** Same as TC-09; Google Chrome installed.

| Step | Action | Expected result |
|---|---|---|
| 1 | Select one client; Run → Download / Request TIS & AIS | Batch Progress opens |
| 2 | Observe | Status cycles through AIS portal → FY selection → AIS downloaded → TIS downloaded |
| 3 | Output folder | Contains `<PAN>-AIS-<FY>.pdf` and `<PAN>-TIS-<FY>.pdf`, both unlocked |

---

## TC-11 — Invalid password fast-fail

| Step | Action | Expected result |
|---|---|---|
| 1 | Add a client with a known-wrong portal password | — |
| 2 | Run any download against that client | Status shows `❌ Failed — Invalid Password...` within ~15 seconds; batch continues to next client |

---

## TC-12 — 2FA account fast-fail

| Step | Action | Expected result |
|---|---|---|
| 1 | Add a client whose ITD account has 2FA enabled | — |
| 2 | Run any download | Status shows `❌ Failed — AUTHENTICATION FAILED: This account has 2FA enabled...` within ~10 seconds |

---

## TC-13 — Stop and Resume

| Step | Action | Expected result |
|---|---|---|
| 1 | Start a batch of 3+ clients | Batch Progress opens |
| 2 | Click Stop during the second client | Active task cancels; all pending rows show ⏹ Stopped; Stop button becomes ▶ Resume |
| 3 | Click Resume | Only incomplete clients are retried; already-completed clients retain their status |

---

## TC-14 — Batch Excel report

| Step | Action | Expected result |
|---|---|---|
| 1 | Run a batch to completion | "⬇ Download Report" button becomes enabled |
| 2 | Click Download Report → choose save path | `.xlsx` saved and opened automatically |
| 3 | Inspect file | Columns: Client Name, Save Folder (hyperlink), Status, Timestamp — one row per client, each with its own timestamp |

---

## TC-15 — Theme switching

| Step | Action | Expected result |
|---|---|---|
| 1 | Settings → Appearance → Dark Navy | All UI elements switch to dark theme instantly; no restart |
| 2 | Relaunch app | Dark Navy theme is preserved |
| 3 | Switch back to Light | All elements revert; no visual artefacts |

---

## TC-16 — Download history persists

| Step | Action | Expected result |
|---|---|---|
| 1 | Complete a successful download for a client | Last Download Status and Last Saved Location columns update |
| 2 | Relaunch app; select the same AY | Columns still show the last result |
| 3 | Switch to a different AY | Columns show that AY's history (or blank if never downloaded) |

---

## TC-17 — Headless vs visible mode

| Step | Action | Expected result |
|---|---|---|
| 1 | Ensure "Run in background" (headless) is checked | Download runs with no visible browser window |
| 2 | Uncheck it; start a download | Chrome window opens visibly; download completes normally |

---

## TC-18 — macOS: AY dropdown does not close immediately

*macOS only.*

| Step | Action | Expected result |
|---|---|---|
| 1 | Click the AY dropdown | Popup opens and stays open for at least 300 ms |
| 2 | Click a year entry | Year is selected; dropdown closes cleanly |

---

## Known limitations (not test failures)

- AIS JSON download is not implemented (CAPTCHA-gated) — F-08 in backlog.
- Large 26AS (TRACES shows "on-demand" message) cannot be downloaded automatically — B-07 in backlog.
- Accounts with 2FA cannot be automated — expected behaviour per E-02.
