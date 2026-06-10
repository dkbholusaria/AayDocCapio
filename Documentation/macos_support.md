# macOS Support

AayDocCapio now runs natively on macOS (tested on macOS 15.5 "Sequoia",
Apple Silicon / arm64, Python 3.14). All features work identically to
Windows and Linux:

| Feature | Status on macOS |
|---|---|
| 26AS bulk download | ✅ Works (bundled Chromium or real Chrome) |
| AIS / TIS request & download | ✅ Works (launches installed Google Chrome via `channel="chrome"`) |
| Encrypted vault (Fernet/AES-128) | ✅ Works |
| PDF password removal (pikepdf) | ✅ Works — the pikepdf wheel bundles libqpdf, no system qpdf needed |
| Excel bulk import / template (openpyxl) | ✅ Works |
| PyQt6 GUI | ✅ Works, light theme enforced (see below) |

---

## Quick Start (macOS)

```bash
git clone https://github.com/dkbholusaria/AayDocCapio.git
cd AayDocCapio
bash scripts/setup.sh        # creates .venv, installs deps + Playwright Chromium
source .venv/bin/activate
python app.py
```

`scripts/setup.sh` works unchanged on macOS — no separate setup script is
needed.

For a double-clickable launcher, use the included `AayDocCapio.command`
(Finder → double-click). It activates the project's `.venv` and starts the
app.

> **Requires Google Chrome** for AIS/TIS downloads, same as on Windows.
> Install from <https://www.google.com/chrome/>. 26AS works without it.

---

## What Changed for macOS

The codebase was already largely cross-platform (pure-Python, PyQt6 +
Playwright, no Windows-only APIs such as `winreg` or `os.startfile`). The
following targeted changes were made; none of them alter behaviour on
Windows or Linux.

### 1. Platform-correct data directories (`app.py`, `automation/browser.py`)

Frozen (compiled) builds now store user data and Playwright browser
binaries in the macOS-conventional location:

| Platform | User data & browsers |
|---|---|
| Windows | `%LOCALAPPDATA%\AayDocCapio` |
| **macOS** | **`~/Library/Application Support/AayDocCapio`** |
| Linux/WSL | `~/.local/share/AayDocCapio` |

When running from source (the normal case), data still lives next to
`app.py`, exactly as before.

### 2. Font handling (`app.py`)

The stylesheet listed `'Segoe UI'` and `'Cascadia Code'` first — both are
Windows-only fonts. On macOS this triggered Qt's font-alias scan on every
startup (~150–200 ms penalty per missing family) and fell back to
arbitrary fonts.

- UI font: `Segoe UI` on Windows → **Avenir Next** elsewhere (already
  bundled in `resources/fonts/`).
- Monospace log font: `Cascadia Code`/`Consolas` on Windows → **Menlo** on
  macOS.
- The generic `sans-serif` token is dropped from the stylesheet on macOS
  only, where Qt resolves it by scanning every installed font.

### 3. Dark-mode protection (`app.py`)

The app's stylesheet assumes a light theme. With macOS in Dark Mode,
unstyled widgets (dialogs, menus, headers) inherited the dark system
palette, producing illegible black-on-black / white-on-white mixes. The
application now pins the Qt color scheme to Light at startup:

```python
app.styleHints().setColorScheme(Qt.ColorScheme.Light)
```

Wrapped in `try/except AttributeError` so Qt builds older than 6.8 are
unaffected.

### 4. Combo-box popup fix (`app.py`)

macOS opens combo-box popups on **mouse-press**; the release of that same
click then lands inside the popup list. The custom
`_ComboListView.mouseReleaseEvent` (a Windows hover-reliability
workaround) interpreted that release as a selection click and instantly
closed the popup — the Assessment Year dropdown appeared to "vanish".
Releases arriving within 300 ms of the popup opening are now ignored,
matching Qt's own internal guard.

### 5. macOS launcher (`AayDocCapio.command`)

A two-line shell launcher so the app can be started from Finder without a
terminal.

---

## Building a Standalone macOS App (optional)

Nuitka can build a macOS app bundle the same way as the Windows build
described in [windows_build.md](windows_build.md):

```bash
pip install nuitka ordered-set zstandard
python -m nuitka \
  --standalone \
  --macos-create-app-bundle \
  --enable-plugin=pyqt6 \
  --include-data-dir=resources=resources \
  --include-data-files=assessment_years.json=assessment_years.json \
  --macos-app-icon=resources/app_icon.png \
  app.py
```

Notes:

- The frozen build will use `~/Library/Application Support/AayDocCapio`
  for the vault, settings, and Playwright browsers (see §1).
- For distribution outside your own machine the bundle must be
  code-signed and notarized (Apple Developer ID), otherwise Gatekeeper
  blocks it. For personal/office use, right-click → Open bypasses the
  warning once.

---

## Known macOS-Specific Notes

- **First launch of Chromium** downloaded by Playwright may prompt macOS
  Gatekeeper; allow it once.
- **Screen Recording / Accessibility permissions** are *not* required —
  the app drives Chrome via Playwright's DevTools protocol, not the
  GUI.
- Apple Silicon (arm64) and Intel (x86_64) are both supported; Playwright
  downloads the matching Chromium build automatically.
