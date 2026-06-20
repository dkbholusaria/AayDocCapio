# Plan: User Help Manual — AayDocCapio v1.6.3

## Context

Users have no in-app reference for learning the app. A bundled HTML user manual opens in the browser
from Help → User Manual, giving CAs a full self-service reference without needing the internet.

---

## Approach

### 1. GitHub Issue

Open a GitHub issue for tracking:
```bash
gh issue create --title "Feature: Bundled HTML User Manual (Help → User Manual)" \
  --label enhancement --label P2 \
  --body "Add a self-contained HTML user manual bundled in resources/, opened via QDesktopServices from Help → User Manual."
```

---

### 2. Create `resources/user_manual.html`

A **single self-contained HTML file** — no external dependencies, no base64 images (logo rendered as styled text, same fallback already used in SMTP help page).

**Visual style: identical to the SMTP Email Setup Help page** (`ui/dialogs.py:1552`):
- Body background: `#F3F6FA` (light)
- Cards/panels: `#FFFFFF` with `rgba(10,22,40,0.09)` borders and subtle box-shadow
- Sticky nav bar: `linear-gradient(90deg,#0d47a1,#1565c0,#1976d2)` — dark blue gradient
- Nav brand: white `AayDoc` + `#B88924` gold `Capio™`
- Section labels: `#B88924` gold, uppercase, letter-spaced (`Plus Jakarta Sans`)
- `<h2>` headings: `#09152A`, `Plus Jakarta Sans` 800
- Body text: `#1A2233`, `Inter` 400
- Accent/links: `#2563EB` blue
- Muted text: `#5A6B84`
- Hero: light gradient + dot-grid pattern, dark navy badge
- Alt sections: `rgba(241,245,251,0.85)` — same `section.alt` pattern
- Footer strip: `linear-gradient(90deg,#0A1628,#0F3A68,#0A1628)` with gold highlight
- Font imports: `Inter` + `Plus Jakarta Sans` from Google Fonts (same `<link>` tags)
- Card hover: lift `-4px` + glow + fluent reveal mouse-tracking gradient (same JS)
- Numbered step circles: `linear-gradient(135deg,#2563EB,#0078D4)` white text
- Bullet dots: `#2563EB`
- Warn boxes: amber `#FEF3C7` / `#FCD34D` / `#92400E`
- Info/tip boxes: same style, green tint (`#ECFDF5` / `#6EE7B7`)
- Code badges: `rgba(15,58,104,0.08)` bg, `#0F3A68` text, `Consolas` font
- Top accent bar on cards: `linear-gradient(90deg,#0F3A68,#0078D4,#B88924)`

**Page structure** (same scaffold as SMTP help):
```
sticky nav  →  hero section  →  alternating content sections  →  footer strip
```

**Sections to cover** (rendered as alternating `<section>` / `<section class="alt">`):

| # | Section | Content |
|---|---------|---------|
| 1 | Overview | What AayDocCapio does; no-cloud privacy guarantee; supported documents |
| 2 | Getting Started | System requirements (Windows, real Chrome), first launch, vault creation |
| 3 | Client Vault | Add/edit/delete clients; PAN, Name, Password, DOB fields; why DOB matters |
| 4 | Bulk Download | Select clients, choose AY, Download Types (26AS/AIS/TIS), run batch; progress dialog; status icons (✅ ❌ ⚠️ ⬜ 🕐) |
| 5 | Form 26AS | What it is; TXT+PDF variants; unlock password format (`DDMMYYYY`) |
| 6 | AIS & TIS | What they are; Phase 1 (instant) vs Phase 2 (queued/Activity History); unlock password format (`lowercase_pan + DDMMYYYY`) |
| 7 | PDF Unlock | 9 password candidates tried automatically; when it fails (wrong DOB); how to fix |
| 8 | Import / Export | Export vault to Excel template; import clients from Excel; bulk onboarding |
| 9 | Tools Menu | Convert 26AS TXT → Excel+HTML; Convert AIS JSON → Excel (capital gains workbook) |
| 10 | Mail Docs to Clients | SMTP setup; test email; bulk send; attachment types |
| 11 | Settings & Themes | Download folder; assessment years; Light/Dark Navy/Slate/Teal themes; how to switch |
| 12 | Check for Updates | Manual update check; what happens when a new version is available |
| 13 | FAQ / Troubleshooting | Table of common issues — same `<table class="trouble">` style as SMTP page |

**Reused helper patterns from SMTP page:**
- `steps_html()` — numbered circles + text items
- `bullets_html()` — blue dot bullets
- `warn_box()` — amber warning callout
- `tip_box()` — green info callout (new, same structure as warn_box)
- `badge()` — inline code badge
- `lnk()` — external link
- Section card pattern (`.prov-card` reused as `.feature-card`)
- Fluent reveal JS (mouse-tracking gradient on cards)

---

### 3. Wire up `Help → User Manual` in `app.py`

**Location:** `app.py` lines 210–222 (Help menu block)

Add the new action **before** "Email Setup Help…" as the first item:

```python
# Help menu
help_menu = menubar.addMenu("Help")

# NEW — User Manual (first item)
act_manual = QAction(_micon("menu_about.png"), "User Manual", self)
act_manual.triggered.connect(self._open_user_manual)
help_menu.addAction(act_manual)
help_menu.addSeparator()          # ← new separator after manual

smtp_help_action = QAction(_micon("btn_send_test.png"), "Email Setup Help…", self)
...
```

**New method** added near `_open_smtp_help` (~line 406):

```python
def _open_user_manual(self):
    from config import _bundled_dir
    from PyQt6.QtGui import QDesktopServices
    from PyQt6.QtCore import QUrl
    path = os.path.join(_bundled_dir(), "resources", "user_manual.html")
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
```

Note: uses `QDesktopServices.openUrl` (not `webbrowser`) as specified in the task. Consistent with the requirement and works correctly from Nuitka-compiled exe.

---

### 4. Nuitka bundling

No change needed. The Nuitka build command already includes:
```
--include-data-dir=resources=resources
```
This means `resources/user_manual.html` is automatically bundled — zero build-script changes required.

---

### 5. Plans/ file

Save this plan as `Plans/user_manual_plan.md` (untracked, per AGENT.md convention).

---

## Critical Files

| File | Change |
|------|--------|
| `resources/user_manual.html` | **Create** — full self-contained HTML manual |
| `app.py` lines 210–222 | **Edit** — add "User Manual" QAction to Help menu |
| `app.py` ~line 406 | **Edit** — add `_open_user_manual()` method |

No other files need changes. Build scripts pick up `resources/` automatically.

---

## Verification

1. Run `python app.py` from the project root
2. Click **Help → User Manual** — browser opens `resources/user_manual.html`
3. Confirm all 14 sections render correctly with dark navy styling
4. Confirm sidebar nav links scroll to correct sections
5. Confirm FAQ `<details>` items expand/collapse
6. Confirm the file is self-contained (no 404s in browser DevTools Network tab)
