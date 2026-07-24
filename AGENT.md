# AayDocCapio — Developer Guide & AI Agent Guidelines

AayDocCapio is a PyQt6 desktop app for Indian CAs and tax professionals. It automates bulk download of Form 26AS, AIS, and TIS from the ITD e-Filing portal (`eportal.incometax.gov.in`) using Playwright browser automation. All client credentials are stored locally in an AES-128 encrypted vault — nothing is uploaded anywhere.

---

## AI Agent Response & Workflow Guidelines

### Mandatory workflow for every feature / bug fix / debug request

Follow these steps in order — no step is optional:

1. **Open a GitHub issue** — before anything else, create a GitHub issue for the task (`gh issue create`). Use the appropriate label (`bug`, `enhancement`,'Feature') and priority (`P1`/`P2`/`P3`). Record the issue number.
   - Every issue body must mention the creation/report date in `YYYY-MM-DD` format.
2. **Plan** — prepare an implementation plan, save it as a `.md` file in the untracked `PlansofThisProject/` subfolder, and get user approval before writing any code.
   - Plan filenames must start with the issue number prefix: `F-<n>_<description>.md`, `B-<n>_<description>.md`, etc. (e.g. `F-13_last_20_log_history.md`).
3. **Implement** — build the feature or fix following the approved plan.
4. **Update documentation** — update `Documentation/ISSUES_BACKLOG.md` and any other relevant files in `Documentation/` to reflect the completed work.
5. **Close the issue** — before closing any GitHub issue, add a closing comment that states what changed, the verification performed, and the commit SHA or PR reference when available. Then close the GitHub issue (`gh issue close <number>`) once the implementation is done and verified.

### General guidelines

- **Plain English Only:** When explaining anything to the user (what a bug was, what changed, how something works, status updates), use plain, everyday language — not technical/programming jargon (no "race condition," "synchronous," internal variable/function names, etc.). The user is non-technical. Only use technical terms if the user explicitly asks for the technical explanation. This does not apply to the code itself, commit messages, or code comments — only to what's said to the user in conversation.
- **Concise Responses:** Avoid long conversational padding.

- **No Trailing Summaries:** Do not append summary sections at the end of responses.
- **No Emojis:** Do not use emojis in responses unless explicitly requested.
- **Proactive Execution:** Proactively run test/verification commands to ensure correctness.
- **Active Python Path:** Always use the explicit `.venv/bin/python` interpreter.
- **Adding Packages:** Verify the project dependency manager first (default to `venv + pip` and update `requirements.txt` via `pip freeze > requirements.txt`).
- **Compact Context:** Compact the context from time to time by summarizing findings or archiving logs to save tokens.

---

## Project Layout

```
AayDocCapio/
├── app.py                      # Single-file UI — main window, all Qt widgets
├── version.py                  # Single source of truth: __version__ = "X.Y.Z"
├── themes.py                   # ThemeColors dataclass, light/dark theme builders
├── vault.py                    # Encrypted client vault (AES-128 Fernet)
├── config.py                   # App paths (_app_dir, _default_download_dir)
├── utils.py                    # Shared utilities (get_timestamp, etc.)
├── as26_converter.py           # 26AS TXT → Excel + HTML converter
├── assessment_years.json       # AY list with enabled/disabled flags
├── requirements.txt            # Runtime pip dependencies
├── automation/
│   ├── auth.py                 # ITD portal login (Playwright, async)
│   ├── browser.py              # Chrome/Chromium launch + context factory
│   ├── downloader.py           # Batch orchestrator, per-client worker
│   ├── downloader_26as.py      # Form 26AS download flow
│   ├── downloader_ais_tis.py   # AIS + TIS download flow (see details below)
│   └── pdf_unlocker.py         # pikepdf-based PDF password remover
├── ui/
│   ├── widgets.py              # Reusable Qt widgets
│   ├── dialogs.py              # Modal dialogs
│   └── helpers.py              # UI helper functions
├── scripts/
│   ├── bump.sh                 # Version bump helper
│   ├── release.sh              # Full release automation (Linux/WSL)
│   ├── setup.sh                # Dev environment setup (Linux/macOS)
│   ├── setup_and_build.ps1     # Windows build (Nuitka + Inno + WiX)
│   ├── installer.iss           # Inno Setup script (EXE installer)
│   └── installer.wxs           # WiX MSI script
├── resources/                  # Icons, fonts, installer graphics
├── docs/                       # GitHub Pages landing page (index.html)
└── Documentation/              # ADRs, PRD, build guides, backlog
```

---

## Key Architecture Decisions

- **PyQt6** for UI — `QTableWidget` for client grid, `QDialog` for modals, stylesheet-based theming. Do not switch to tkinter or CustomTkinter.
- **Playwright async** for browser automation — each client gets an isolated `BrowserContext`. Never share contexts between clients.
- **Real Google Chrome** (`channel="chrome"`) is required for AIS/TIS downloads. Bundled Chromium silently fails on the AIS portal. 26AS works with either.
- **Fixed viewport 1600×900** — the ITD portal layout breaks at narrower sizes.
- **`asyncio.run()` in a background `QThread`** — keeps the Qt event loop alive during downloads. Never call Qt widgets from the worker thread; use signals.
- **`selected_ids` set** is the source of truth for client selection state. Checkbox visual state and count label must always be derived from this set, never the other way around.
- **Theme detection** — use `getattr(_t(), "name", "").lower() != "light"` to check for dark mode. `_t()` returns the active `ThemeColors` instance.

---

## AIS / TIS Download Flow

### Two phases

**Phase 1 — `run_request_ais()` in `downloader_ais_tis.py`**

- Opens the AIS portal, selects the FY, clicks "Request PDF"
- If AIS is ready instantly → downloads it, unlocks it
- Also downloads TIS immediately (TIS is always available at request time)
- Ends by calling `status_callback(combined_status_label(ais_outcome, tis_outcome))`
- Returns the `ais_outcome` dict with `ais_outcome["tis"] = tis_outcome`

**Phase 2 — `run_download_ais_tis()` in `downloader_ais_tis.py`**

- Used when Phase 1 queued AIS for generation ("Activity History" mode)
- Fetches AIS PDF from the Activity History section
- Ends by calling `status_callback(combined_status_label(ais_outcome, tis_outcome))`
- Returns `{"ais": ais_outcome, "tis": tis_outcome}`

### Outcome dict pattern

Every document result is a dict created by `_outcome()`:

```python
def _outcome(status, unlocked=None, reason=None, **extra):
    return {"status": status, "unlocked": unlocked, "reason": reason, **extra}
```

**Status values:** `"downloaded"`, `"requested"`, `"too_large"`, `"no_data"`, `"not_found"`, `"timeout"`, `"aborted"`, `"skipped"`, `"already_present"`, `"failed"`

**`unlocked` field:** `True` = PDF unlocked, `False` = unlock failed (wrong password), `None` = not attempted

### Status display

```python
def _doc_label(o, name):   # e.g. "AIS" or "TIS"
    # Returns e.g. "✅ AIS unlocked", "⚠️ TIS locked — wrong password", "⬜ AIS — no data for this FY"

def combined_status_label(ais_o, tis_o):
    # Returns e.g. "⚠️ AIS locked — wrong password | ✅ TIS unlocked"
```

### Critical detection order in AIS polling loop

When polling the modal for AIS status, check in this exact order:

1. `"don't have any|do not have any"` → `_outcome("no_data")` — MUST be first
2. `"too large|unable to generate as pdf"` → `_outcome("too_large")` — but NOT `"ais utility"` (that string is always present in modal)
3. `"reference id|activity history|submitted successfully"` → `_outcome("requested")`

---

## Status Callback Architecture

There are TWO distinct `set_status` functions in `app.py` — don't confuse them:

### Local `set_status(pan, text)` — inside the batch runner

```python
def set_status(pan, text):
    if self._progress_dialog:
        self._progress_dialog.set_status(pan, text)          # updates batch progress dialog
    terminal = ("✅", "❌", "🕐", "⏹", "⬜", "⚠")           # ⚠ is REQUIRED here
    if ay_label and any(text.startswith(p) for p in terminal):
        self.vault.record_download(pan, ay_label, text, path) # persists to vault
```

**Critical:** The `⚠` prefix MUST be in the terminal list. Without it, `"⚠️ AIS locked — wrong password | ⚠️ TIS locked — wrong password"` never gets saved to the vault, so the main grid keeps showing the old status from a previous run.

---

## PDF Unlock

**Password format (ITD convention):**

- AIS / TIS: `lowercase_pan + DDMMYYYY` e.g. `aekpb0205l12121976`
- Form 26AS: `DDMMYYYY` (DOB only, no PAN)

**9 candidates tried** (`pdf_unlocker.py`):
3 DOB formats × 3 PAN variants:

- DOB formats: `DDMMYYYY`, `DDMMYY`, `DD/MM/YYYY`
- PAN variants: lowercase PAN + DOB, DOB only, UPPERCASE PAN + DOB

---

## Vault

`vault.py` — AES-128 Fernet encryption, stored in `tax_vault.json`.

Key methods:

```python
vault.get_clients()                          # → list of {pan, name, password, dob, ...}
vault.save_client(pan, name, pwd, dob)       # add/update
vault.record_download(pan, ay, status, path) # persist download status
vault.get_download_history(ay_label)         # → {pan: {status, path, ts}}
```

---

## Versioning

**Single source of truth:** `version.py`

```python
__version__ = "1.6.3"   # ← only file to edit when bumping
```

To bump version:

```bash
bash scripts/bump.sh patch    # X.Y.Z → X.Y.(Z+1)
bash scripts/bump.sh minor    # X.Y.Z → X.(Y+1).0
bash scripts/bump.sh 1.7.0    # exact version
```

---

## Release Workflow

> **Trigger phrase:** When the user says something like "let's bump the version", "time to release", "bump to X.Y.Z", or "new release", follow this checklist in full. No steps are optional.

### Step 1 — Bump `version.py`

```bash
bash scripts/bump.sh X.Y.Z    # sets exact version, e.g. bash scripts/bump.sh 1.7.0
```

This is the single source of truth. Build scripts (`setup_and_build.ps1`, `release.sh`) pick it up automatically.

### Step 2 — Update `CHANGELOG.md` and `Documentation/CHANGELOG.md`

Prepend a new release block above the previous `[X.Y.Z]` entry in **both files**:

```markdown
## [X.Y.Z] — YYYY-MM-DD

### New Features
#### <Feature Name>
- **<Feature>** — <description>

### Improvements
- ...

### Bug Fixes
- ...

---
```

Ask the user what bullet points to include, or auto-generate based on the feature description they provide. Always include the consolidation/consolidated sheet note if the JSON-to-Excel converter was changed.

### Step 3 — Update `README.md` and `Documentation/README.md`

In **both files**:

- Version badge on line 3: `**vOLD**` → `**vNEW**`
- Section heading: `## What's New in OLD` → `## What's New in NEW`
- Replace the What's New body with a concise summary of the new release (matching CHANGELOG bullets, shorter form)

### Step 4 — Update `docs/index.html`

Two sub-tasks:

**A. Version bump** — replace ALL occurrences of the old version string and date:

```bash
sed -i 's/vOLD/vNEW/g; s/OLD.VERSION/NEW.VERSION/g; s/DD Mon YYYY/DD Mon YYYY/g' docs/index.html
```

Then verify with: `grep -n "OLD" docs/index.html`

Locations to check: release badge, all download hrefs (`.exe`, `.msi`, macOS `.zip`), `<h2>` in What's New, installer filename references in prose (upgrade notice, install instructions, SmartScreen walkthrough).

**B. What's New section** — replace the entire `<div class="change-list">` block inside `<section id="whats-new">` with new `<div class="change-item">` entries matching the new release features.

**C. New feature card (if applicable)** — if a new user-facing capability was added, add a `<div class="card">` to the Features section (`<div class="cards">`, ~line 968). Follow the existing card pattern:

```html
<div class="card">
  <span class="card-icon">EMOJI</span>
  <h3>Feature Name</h3>
  <p>One or two sentences describing the feature for a new visitor.</p>
</div>
```

### Step 5 — Update `pyproject.toml`

```
version = "OLD"  →  version = "NEW"
```

This file is not used in the active build pipeline but must stay consistent.

### Step 6 — Verify

```bash
# Should return zero matches (CHANGELOG historical entries and AGENT.md example are expected)
grep -r "OLD_VERSION" --include="*.py" --include="*.md" --include="*.html" --include="*.toml" .

# Confirm live version
python3 -c "from version import __version__; print(__version__)"
```

### Step 7 — Commit and push to main

Stage all changed files, commit with a descriptive message, and push directly to `main`:

```bash
git add <files>
git commit -m "feat: <description> + vX.Y.Z release"
git push origin main
```

### Step 8 — Build & Release

```bash
# Build Windows installers (run from PowerShell on Windows machine):
powershell -ExecutionPolicy Bypass -File "\\wsl.localhost\Ubuntu-24.04\home\deepak\projects\AayDocCapio\scripts\setup_and_build.ps1"
# Run the release script from WSL:
bash scripts/release.sh
```

### Files NOT touched during a version bump

- `scripts/bump.sh`, `scripts/release.sh`, `scripts/setup_and_build.ps1` — read `version.py` dynamically
- `scripts/installer.iss`, `scripts/installer.wxs` — version injected at build time via template variables
- `AGENT.md` example version strings — illustrative only, update manually only when keeping docs current

---

## Release Announcements

> **Trigger phrase:** When the user says something like "announce the release", "post about this release", "write WhatsApp/LinkedIn message", "flyer", "draft announcement", generate the prompts below and hand them to the user to run in ChatGPT or NanoBanana.

### Step 1 — Gather inputs from CHANGELOG.md

Read the latest `## [X.Y.Z]` block from `Documentation/CHANGELOG.md` and extract:

- Version number and date
- Feature names and one-line descriptions
- Audience impact (what CAs/tax professionals can now do)

### Step 2A — Generate text announcement prompt

Hand the user the following filled-in prompt to paste into ChatGPT / NanoBanana for **WhatsApp + LinkedIn text**:

---

**TEXT PROMPT TEMPLATE** (fill `[VERSION]`, `[DATE]`, and `[FEATURES]` before handing to the user):

```text
You are a product communications specialist writing for an Indian CA / tax professional audience.

Product: AayDocCapio — a Windows desktop app for Indian CAs that automates bulk download of Form 26AS, AIS, and TIS from the ITD e-Filing portal. All data stays local; nothing is uploaded anywhere.

New release: v[VERSION] — [DATE]

Key new features:
[FEATURES — paste bullet points from CHANGELOG verbatim]

Write TWO announcements:

---

1. WHATSAPP MESSAGE
- Audience: CA colleagues and clients in a WhatsApp group
- Tone: warm, conversational, professional — like a message from a trusted colleague
- Length: 5–8 lines max, no more
- Format: plain text, minimal formatting (a few line breaks, maybe 1–2 bold phrases using *asterisks*)
- Open with the biggest benefit, not the version number
- End with a soft call-to-action (e.g. "Let me know if you'd like to try it")
- Do NOT use hashtags
- Do NOT use emojis unless they add genuine clarity (1–2 max if used)

---

2. LINKEDIN POST
- Audience: Indian CAs, tax professionals, fintech followers on LinkedIn
- Tone: professional, proud, clear — founder sharing a milestone
- Length: 150–200 words
- Format: short punchy opening line (no "Excited to announce"), then 3–4 bullet points of key features, then a closing line
- Use line breaks generously for readability
- End with 4–6 relevant hashtags (#AayDocCapio #IncomeTax #CA #TaxTech #ITD or similar)
- Do NOT start with "I am excited" or "Thrilled to share"

---

Keep both grounded in concrete CA workflow benefits — what pain does this solve, what time does it save. Avoid marketing fluff.
```

---

### Step 2B — Generate flyer image prompt

Hand the user the following filled-in prompt to paste into **ChatGPT (DALL·E / GPT-4o image gen) or NanoBanana** for a shareable visual flyer:

---

**FLYER PROMPT TEMPLATE** (fill `[VERSION]`, `[DATE]`, `[HERO]`, `[SUBHERO]`, `[MOCKUP_DESCRIPTION]`, `[FLOW_ITEMS]`, and `[FEATURES]` before handing to the user):

```text
Create a professional product release announcement flyer as a portrait image (1080 × 1350 px), suitable for WhatsApp and LinkedIn.

─── BRAND & PALETTE ───
Product name: AayDocCapio (render as "AayDoc Capio™" — "AayDoc" in white, "Capio" in electric blue #2979FF)
Background: deep navy #0A1628, full bleed
Primary accent: electric blue #2979FF (headlines, highlights, arrows, links)
Body text: white #FFFFFF
Secondary text: light grey #B0BEC5
Typography: Inter or similar clean geometric sans-serif — NO script, NO decorative fonts

─── THREE-ZONE LAYOUT (top to bottom) ───

ZONE 1 — HEADLINE (top ~35% of image, left-aligned, 60px left/right padding)
- Hero headline: large, bold, white, ~72px, 2–3 lines
  [HERO — e.g. "Now Convert\nAIS JSON —\nto Excel"]
  (key word or phrase on its own line in electric blue #2979FF, bold)
- Blue underline accent bar (~60px wide, 3px tall) below the last hero line
- Sub-headline: white, ~24px, normal weight
  [SUBHERO — e.g. "Full capital gains workbook generated in one click"]
- Email provider / tool logos row (small icon + label pairs, ~28px tall, separated by bullet dots):
  [FLOW_ITEMS — e.g. icon labels like "TDS/TCS • Salary • SFT • Dividends • More"]

ZONE 2 — CENTRAL VISUAL MOCKUP (middle ~40% of image)
- A dark laptop (MacBook Pro style, no logo) shown at a slight upward angle, left-of-center
- The laptop screen shows a simplified UI mockup of [MOCKUP_DESCRIPTION]
  Use dark sidebar (#0F2040) with white menu labels; main panel lighter navy (#162033); blue active item highlight
- From the laptop screen, 3–4 glowing blue curved arrows radiate to the right toward output cards:
  [OUTPUT_CARDS — e.g. 3–4 rounded dark cards, each with an icon + short label like "STCG Sheet ✓", "Capital Market (All) ✓", "Audit Trail ✓", "ReadMe – Capital Gains ✓"]
  Each card has a small green checkmark badge (✓ in green circle) on its right edge
- Floating file icons mid-flight along the arrows: PDF icon, Excel (green X) icon

ZONE 3 — BRANDING FOOTER (bottom ~25%, slightly lighter navy #0D1E35, centered)
- Product wordmark large: "AayDoc" (white, bold, ~52px) + "Capio™" (electric blue, bold, ~52px)
- Thin blue divider line (~120px wide) below wordmark
- Tagline: "Tax Documents. [TAGLINE_HIGHLIGHT]" — highlighted word(s) in electric blue
  [TAGLINE — e.g. "Tax Documents. Converted to Insights."]

─── EXACT TEXT TO RENDER ───
(Render every word exactly as written — do not paraphrase or omit)

Hero line 1–3: [HERO]
Sub-headline: [SUBHERO]
Flow items row: [FLOW_ITEMS]
Output card labels: [OUTPUT_CARDS]
Footer tagline: [TAGLINE]
Bottom-right corner (tiny, grey): download.aaydoccapio.com

─── RENDERING RULES ───
- Laptop mockup must look realistic — dark aluminium chassis, thin bezel, keyboard visible
- Glowing blue arrows must look like animated data-flow lines (soft neon glow, not flat)
- Output cards: rounded corners (12px), dark fill (#0F2040), thin blue border (#2979FF 40% opacity)
- No drop shadows on text; subtle glow on arrows and card borders only
- No watermarks, no outer frames, no device brand logos
- Output: single flat flyer image, no mockup shell around it
```

---

### Step 3 — Save announcement assets (optional)

If the user asks to save the drafted messages or flyer prompts, save them as `Plans/announcement_vX.Y.Z.md` (untracked, in `.gitignore`'d `Plans/` folder).

---

## Dev Environment Setup

### Linux / macOS / WSL (run from source)

```bash
bash scripts/setup.sh        # creates .venv, installs deps, installs Playwright Chromium
source .venv/bin/activate
python app.py
```

### Windows (run from source)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python app.py
```

---

## Runtime Dependencies

| Package | Purpose |
|---|---|
| `PyQt6>=6.11.0` | Desktop GUI framework |
| `playwright>=1.60.0` | Browser automation |
| `cryptography>=48.0.0` | AES-128 Fernet vault encryption |
| `pikepdf>=10.7.2` | PDF password removal |
| `openpyxl>=3.1.5` | Excel bulk-import / vault template generation |
| `xlsxwriter>=3.2.0` | 26AS converter — streaming writer for large files |
| `pillow>=12.2.0` | Custom checkbox image generation |

---

## Windows Build Prerequisites

| Tool | Purpose | How to get |
|---|---|---|
| Nuitka | Python → native exe | `pip install nuitka ordered-set zstandard` |
| Inno Setup 6+ | `.exe` installer | jrsoftware.org/isdl.php |
| .NET 8 SDK | Required by WiX | dotnet.microsoft.com/download |
| WiX Toolset v4+ | `.msi` installer | `dotnet tool install --global wix` |
| WixToolset.UI.wixext | Wizard UI | `wix extension add WixToolset.UI.wixext --global` |

---

## Coding Conventions

### Theme-aware colors

Always use `ThemeColors` fields — never hardcode hex colors:

```python
from themes import _t
_bt = _t()
item.setForeground(QColor(_bt.text_primary))
item.setBackground(QColor(_bt.bg_table))
```

### Selection state

`self.selected_ids` (a `set`) is always the authoritative selection state. Never modify it during row filtering — only hide rows.

### Thread safety

Download workers run in a `QThread`. Update UI only via Qt signals — never call widget methods from a worker thread directly.

---

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| AIS/TIS downloads silently fail | Must use `channel="chrome"` (real Chrome), not bundled Chromium |
| `expect_download` never fires | Call it on `Page`, not `BrowserContext` |
| Portal never reaches `networkidle` | Use `wait_until="domcontentloaded"` + `asyncio.sleep(3)` |
| AIS "no data" misclassified as "queued" | Check `"don't have any"` BEFORE `"activity history"` in the polling loop |
| AIS always flagged "too large" | Don't include `"ais utility"` in the too-large regex — it's always present in the modal |
| `⚠️` statuses not shown in main grid | `"⚠"` must be in terminal prefixes in local `set_status` |
| PDF unlock fails | Verify DOB in vault matches PAN card exactly (DD-MM-YYYY format) |

---

## Session Memory & Lessons Learned

### Capital Market Consolidated Sheet

- **Blueprint Structure:** The revised `⭐ Capital Market (All)` sheet contains exactly 30 columns (shifted left to start at Column A, removing the blueprint's margin space column A). The freeze pane is set to lock headers (top 2 rows) and the first 11 columns (up to `Security Class` Column K).

- **Cell-by-Cell Linkage:** Raw data columns are linked directly to individual SFT sheets using Excel formulas (e.g. `='SFT-17-LES(M) (Eq Sale)'!B12`). Column mapping is dynamically resolved for depository (SFT-17), RTA (SFT-18), and off-market (SFT-17-LES(OC)) sheets.
- **Grandfathering & Gain Formulas (Excel-driven):**
  - `Assets Eligible for GrandFathering` (Col U): `=IF(AND(ISNUMBER(SEARCH("Long", L{xr})), OR(K{xr}="Listed Equity Share", K{xr}="Unit of Equity Oriented Mutual Fund", K{xr}="Unit of Business Trust", AND(K{xr}="Other Units", S{xr}>0))), "Yes - Eligible", IF(ISNUMBER(SEARCH("Short", L{xr})), "No - Short term Asset", "No - Ineligible Asset"))`
  - `Effective FMV` (Col V): `=IF(U{xr}="Yes - Eligible", T{xr}, 0)`
  - `Adj. FMV` (Col W): `=MIN(O{xr}, V{xr})`
  - `Adj. Cost of Acquisition` (Col X): `=MAX(Q{xr}, W{xr})`
  - `Capital Gain (w/o Indexation)` (Col Y): `=O{xr}-X{xr}`
  - `Capital Gain (w/ Indexation)` (Col Z): `=O{xr}-R{xr}`
  - `STCG` (Col AA): `=IF(ISNUMBER(SEARCH("Short", L{xr})), Y{xr}, 0)`
  - `LTCG w/o Indexation` (Col AB): `=IF(ISNUMBER(SEARCH("Long", L{xr})), Y{xr}, 0)`
  - `LTCG with Indexation` (Col AC): `=IF(ISNUMBER(SEARCH("Long", L{xr})), Z{xr}, 0)`
- **Defined Names:** Register workbook-scoped defined names pointing to entire columns for formula validation: `CostWoIndex` ($Q:$Q), `CostWIndex` ($R:$R), `EligibleAssetForGF` ($U:$U), `AdjustedFMV` ($W:$W), `AdjustedCostWoIndex` ($X:$X), `CapitalGainWoIndex` ($Y:$Y), `CapitalGainWIndex` ($Z:$Z), `STCG` ($AA:$AA), `LTCGWoIndex` ($AB:$AB), and `LTCGWIndex` ($AC:$AC).
- **Gains Visual Treatment:** Long-term gain rows are highlighted using a soft blue background (`#f0f4ff` for standard cells, `#e6f2ff` for formulas) to distinguish them from short-term transactions.
- **Subtotal & Grand Total Formulas:** SFT group subtotal rows use standard `=SUM` formulas. The Grand Total row directly sums these subtotal cells rather than summing ranges to avoid double-counting.
- **Plain-English Explanation Sheet ("ReadMe - Capital Gains"):** A guide sheet in the grey general theme (`#808080`) containing columns: `Column`, `Field Name`, `Plain English Explanation`, and `Tax Reference`. Explains all grandfathering/indexation columns in non-formula language for client transparency. Explicitly documents the post-23-Jul-2024 budget rule (abolition of indexation and flat 12.5% LTCG rate). Includes a prominent legal disclaimer block styled in soft red (`#F2DCDB`) stating that the calculations are informational, provided on a best-efforts basis, and do not constitute professional tax advice.

---

## Key Pending Updates & Open Issues

Refer to `Documentation/ISSUES_BACKLOG.md` for the canonical tracker. Key active priorities:

- **B-02 & B-06 (PDF/TXT ZIP Unlock):** Expand DOB formats used for password attempts when unlocking files.
- **F-10 (Large 26AS Direct Downloads):** Implement automated logins to `tdscpc.gov.in` to poll on-demand 26AS requests.
