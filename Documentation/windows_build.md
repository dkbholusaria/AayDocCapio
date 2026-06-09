# AayDocCapio — Windows Build Guide

This document covers all options for building the Windows executable and installer for AayDocCapio.

---

## Overview

The build pipeline has three independent stages:

```text
Stage 1: Compile         Stage 2: Package (.exe)    Stage 3: Package (.msi)
─────────────────        ───────────────────────    ───────────────────────
Python source            Nuitka output folder    →  Inno Setup → Setup.exe
    │                    dist\AayDocCapio\        →  WiX        → App.msi
    └─→ Nuitka ──────→   AayDocCapio.exe
```

- **Stage 1 (Nuitka)** is always required — it produces the standalone exe
- **Stage 2 and 3** are optional — use one or both depending on your distribution needs

---

## Prerequisites

| Tool | Purpose | Install |
| --- | --- | --- |
| Python 3.x | Running the app and Nuitka | python.org |
| Nuitka | Compiles Python → native exe | `pip install nuitka` |
| Inno Setup 6/7 | Builds `.exe` installer | jrsoftware.org/isdl.php |
| .NET 8 SDK | Required by WiX | dotnet.microsoft.com/download |
| WiX Toolset v4+ | Builds `.msi` installer | `dotnet tool install --global wix` |
| WixToolset.UI.wixext | Installer wizard UI | `wix extension add WixToolset.UI.wixext --global` |

Inno Setup and WiX are both optional — you only need the ones you plan to use.

---

## Option A — Automated Full Build (Recommended)

Runs all stages automatically: sets up venv, compiles, and builds both installers.

The script works in two modes — it detects which one to use automatically:

**WSL mode** — project is cloned in WSL, build runs on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File "\\wsl.localhost\Ubuntu-24.04\home\deepak\projects\AayDocCapio\scripts\setup_and_build.ps1"
```

**Windows mode** — project is cloned directly on Windows (`git clone` into a Windows path):

```powershell
cd C:\path\to\AayDocCapio
powershell -ExecutionPolicy Bypass -File scripts\setup_and_build.ps1
```

In Windows mode the sync step is skipped and the build runs in place. In WSL mode the project is first copied to `C:\AayDocCapio-build\`.

What it does:

1. Detects whether to sync from WSL or build in place
2. Creates a Python venv
3. Installs runtime + build dependencies
4. Runs a smoke test (import check)
5. Compiles with Nuitka → `dist\AayDocCapio\`
6. Builds Inno Setup installer → `installer_output\AayDocCapio_Setup_v1.0.0.exe`
7. Builds WiX MSI → `installer_output\AayDocCapio.msi`

Steps 6 and 7 are skipped gracefully if Inno Setup / WiX are not installed.

---

## Option B — Manual Nuitka Compile Only

Use this if you only need the raw compiled folder (no installer).

```powershell
cd C:\AayDocCapio-build

python -m nuitka `
    --standalone `
    --windows-console-mode=disable `
    --windows-icon-from-ico=resources\app_icon.ico `
    --output-dir=dist `
    --output-filename=AayDocCapio.exe `
    --include-data-file=assessment_years.json=assessment_years.json `
    --include-data-dir=resources=resources `
    --include-data-dir=assets=assets `
    --include-package=automation `
    --include-module=vault `
    --enable-plugin=pyqt6 `
    --assume-yes-for-downloads `
    app.py

Rename-Item "dist\app.dist" "AayDocCapio"
```

Output: `dist\AayDocCapio\` — a portable folder you can zip and distribute directly.

---

## Option C — Inno Setup Installer Only

Use this after a Nuitka build when you only want the `.exe` installer.

Prerequisite: Nuitka output exists at `dist\AayDocCapio\`

```powershell
cd C:\AayDocCapio-build
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" scripts\installer.iss
```

Output: `installer_output\AayDocCapio_Setup_v1.0.0.exe`

What the installer does for the end user:

- Runs an install wizard
- Copies app to `C:\Program Files\AayDocCapio\`
- Creates Start Menu and optional Desktop shortcut
- Registers in Windows Add/Remove Programs
- Includes an uninstaller

---

## Option D — WiX MSI Only

Use this after a Nuitka build when you want a proper `.msi` package.

Prerequisite: Nuitka output exists at `dist\AayDocCapio\`, WiX installed.

```powershell
cd C:\AayDocCapio-build
wix eula accept wix7
wix build scripts\installer.wxs -out installer_output\AayDocCapio.msi -ext WixToolset.UI.wixext -arch x64
```

Output: `installer_output\AayDocCapio.msi`

Advantages of MSI over `.exe` installer:

- Standard Windows Installer format — trusted by enterprise IT
- Supports silent/automated install: `msiexec /i AayDocCapio.msi /quiet`
- Supports Group Policy deployment (GPO)
- Built-in repair and upgrade handling

---

## Option E — Batch Script (Quick Local Build)

A simpler `.bat` alternative to the PowerShell script. Does not sync from WSL — run it directly from the project folder on Windows.

```cmd
scripts\build_win.bat
```

Produces the Inno Setup `.exe` installer only. Useful for quick local builds without PowerShell.

---

## Output Files

| File | Description |
| --- | --- |
| `dist\AayDocCapio\AayDocCapio.exe` | Compiled standalone executable |
| `dist\AayDocCapio\*` | Full app folder (portable, no install needed) |
| `installer_output\AayDocCapio_Setup_v1.0.0.exe` | Inno Setup installer for end users |
| `installer_output\AayDocCapio.msi` | WiX MSI for enterprise / silent deployment |

---

## Choosing Between Inno Setup and WiX

| Scenario | Use |
| --- | --- |
| Distributing to individual users | Inno Setup `.exe` — familiar wizard UI |
| Enterprise / IT managed deployment | WiX `.msi` — supports GPO and silent install |
| Both audiences | Build both (the automated script does this) |
| Just testing / internal use | Portable folder (`dist\AayDocCapio\`) — no install needed |

---

## Troubleshooting

### Nuitka: `No module named nuitka`

```powershell
pip install nuitka ordered-set zstandard
```

### WiX error WIX0144: extension not found

The WiX UI extension must be installed separately:

```powershell
wix extension add WixToolset.UI.wixext --global
```

Run once, then always pass `-ext WixToolset.UI.wixext` to `wix build`. The automated script does this automatically.

### WiX: `wix` not recognized

```powershell
# Add .NET tools to PATH for current session
$env:PATH += ";$env:USERPROFILE\.dotnet\tools"
# Make permanent
[Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";$env:USERPROFILE\.dotnet\tools", "User")
```

### WiX error WIX7015: must accept OSMF EULA

WiX v7 requires a one-time EULA acceptance via a separate subcommand:

```powershell
wix eula accept wix7
```

Run this once, then `wix build` works normally. The automated script (`setup_and_build.ps1`) runs this automatically before each build.

### Robocopy exit code 16 (sync failed)

Run the script from inside the scripts folder:

```powershell
cd "\\wsl.localhost\Ubuntu-24.04\home\deepak\projects\AayDocCapio\scripts"
powershell -ExecutionPolicy Bypass -File .\setup_and_build.ps1
```

### PowerShell execution policy error

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Inno Setup: `No files found matching dist\AayDocCapio\*`

Ensure Nuitka has run first and `dist\AayDocCapio\` exists. The installer looks for this folder relative to the project root.

### `msvcp140.dll` warning during Nuitka build

Install the [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) on the build machine. This warning does not prevent the build from completing.
