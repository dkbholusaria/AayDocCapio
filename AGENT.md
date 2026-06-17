# AayDocCapio — Agent Quick Reference

Concise task guide for Claude. For full details see CLAUDE.md.

---

## What is this app?

PyQt6 desktop app for Indian tax professionals. Bulk-downloads Form 26AS, AIS, and TIS from ITD e-Filing portal using Playwright. Client credentials stored in AES-128 encrypted local vault.

**Owner:** Deepak Bholusaria (deepak@bholusaria.com)
**Repo:** github.com/dkbholusaria/AayDocCapio
**Version:** read from `version.py`

---

## How Deepak works

- Commits directly to `main` — no feature branches
- Pushes via `gh` token
- Builds Windows installers locally on Windows (via `setup_and_build.ps1`), macOS via GitHub Actions CI
- Releases via `bash scripts/release.sh` from WSL
- Prefers concise responses — no trailing summaries, no emojis unless asked

---

## Bumping the version

Edit ONE file only:

```bash
bash scripts/bump.sh patch     # 1.5.6 → 1.5.7
bash scripts/bump.sh minor     # 1.5.6 → 1.6.0
bash scripts/bump.sh 2.0.0     # exact
```

Everything else (CI workflows, installers, build scripts) reads `version.py` automatically.
`docs/index.html` and release notes still need manual update.

---

## Releasing

```bash
bash scripts/release.sh          # full release
bash scripts/release.sh --rerun  # re-upload files to existing tag
bash scripts/release.sh --dry-run
```

To upload files manually to a release:
```bash
gh release upload vX.Y.Z file.exe file.msi --repo dkbholusaria/AayDocCapio --clobber
```

---

## Key files to know

| File | What it does |
|---|---|
| `app.py` | Entire UI — 3000+ lines, single file |
| `version.py` | `__version__ = "X.Y.Z"` — single source of truth |
| `vault.py` | Encrypted client store; `record_download()` persists batch status |
| `automation/downloader_ais_tis.py` | AIS + TIS download logic; `_outcome`, `_doc_label`, `combined_status_label` |
| `automation/pdf_unlocker.py` | PDF unlock; tries 9 password candidates |
| `automation/auth.py` | ITD portal login via Playwright |
| `scripts/release.sh` | Full release automation |
| `scripts/bump.sh` | Version bump helper |
| `scripts/setup_and_build.ps1` | Windows build (Nuitka + Inno Setup + WiX) |
| `docs/index.html` | GitHub Pages landing page — update version + date on release |

---

## AIS/TIS status system

Outcomes are dicts: `{"status": ..., "unlocked": True/False/None, "reason": ...}`

Status values: `downloaded`, `requested`, `too_large`, `no_data`, `not_found`, `timeout`, `skipped`, `failed`

Final status shown to user via:
```python
combined_status_label(ais_outcome, tis_outcome)
# → "⚠️ AIS locked — wrong password | ✅ TIS unlocked"
```

**Terminal prefixes** (triggers vault persistence in local `set_status`):
`"✅"  "❌"  "🕐"  "⏹"  "⬜"  "⚠"`  — the `⚠` is critical; without it locked-PDF results never save.

---

## PDF unlock passwords

ITD format: `lowercase_pan + DDMMYYYY` for AIS/TIS; DOB only for 26AS.
9 candidates tried: 3 DOB formats × 3 PAN case variants.
Vault stores DOB as `DD-MM-YYYY`. Unlock fails when vault DOB ≠ ITD's registered DOB.

---

## Browser requirements

- AIS/TIS: **real Google Chrome** (`channel="chrome"`) — bundled Chromium silently fails
- 26AS: works with bundled Chromium
- Viewport must be **1600×900** — portal breaks at smaller sizes

---

## CI workflows

| Workflow | Trigger | Output |
|---|---|---|
| `build-windows.yml` | push tag `v*` or manual | EXE + MSI attached to GitHub Release |
| `build-macos.yml` | push tag `v*` or manual | ZIP attached to GitHub Release |

Trigger manually:
```bash
gh workflow run build-macos.yml --repo dkbholusaria/AayDocCapio --ref main
```

**Known WiX issue:** `wix eula accept wix7` must run before `wix extension add` — not after.

---

## Common bugs & fixes

| Symptom | Root cause | Fix |
|---|---|---|
| AIS always "too large" | `"ais utility"` regex matches permanent modal text | Remove `"ais utility"` from too-large regex |
| "No data" detected as "queued" | Portal "no data" page contains "activity history" text | Check `"don't have any"` BEFORE queued regex |
| TIS times out 60s on "no data" | `expect_download` waits for file that never comes | On timeout, read modal text and check for "no data" |
| Main grid shows old ❌ after ⚠️ run | `"⚠"` missing from terminal prefix list | Add `"⚠"` to terminal tuple in local `set_status` |
| PDF unlock fails | Wrong DOB in vault | Ask user to correct DOB — must match PAN card exactly |
| WiX EULA error in CI | EULA accepted after extension install | Move `wix eula accept wix7` before `wix extension add` |
