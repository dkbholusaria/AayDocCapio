# AayDocCapio - Windows Setup & Build Script
# Run from PowerShell on Windows: .\setup_and_build.ps1
#
# Works in two modes:
#   WSL mode    - project lives in WSL; syncs to C:\AayDocCapio-build\ first
#   Windows mode - project cloned directly on C:\ ; builds in place

$SCRIPT_DIR = $PSScriptRoot
$PROJECT_ROOT_CANDIDATE = Split-Path -Parent $SCRIPT_DIR   # one level up from scripts\

$WSL_SRC  = "\\wsl.localhost\Ubuntu-24.04\home\deepak\projects\AayDocCapio"
$WIN_DEST = "C:\AayDocCapio-build"

Write-Host ""
Write-Host "========================================================"
Write-Host "  AayDocCapio - Setup & Build"
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "========================================================"
Write-Host ""
Write-Host "  Script dir   : $SCRIPT_DIR"
Write-Host "  Project root : $PROJECT_ROOT_CANDIDATE"

# ── Step 1: Locate / sync project files ──────────────────────────
Write-Host ""
Write-Host "--------------------------------------------------------"
Write-Host "[Step 1] Locating project files..."
Write-Host "--------------------------------------------------------"

# Only C:\ is treated as a native Windows path; D:\ and others may be WSL symlink drives
$appPyPath = Join-Path $PROJECT_ROOT_CANDIDATE "app.py"
try { $resolved = (Resolve-Path $PROJECT_ROOT_CANDIDATE -ErrorAction Stop).ProviderPath } catch { $resolved = "" }
$isNativeWindows = ($resolved -match '^C:\\') -and ($resolved -notmatch '^\\\\.+')

Write-Host "  Resolved path    : $resolved"
Write-Host "  Is native Windows: $isNativeWindows"

if ($isNativeWindows -and (Test-Path $appPyPath)) {
    $WIN_DEST = $PROJECT_ROOT_CANDIDATE
    Write-Host "  Mode: Windows clone - building in place at $WIN_DEST"
} else {
    Write-Host "  Mode: WSL source - syncing to $WIN_DEST"
    Write-Host ""
    Write-Host "  Source : $WSL_SRC"
    Write-Host "  Dest   : $WIN_DEST"

    if (-not (Test-Path $WIN_DEST)) {
        Write-Host "  Creating destination directory..."
        New-Item -ItemType Directory -Path $WIN_DEST | Out-Null
    }

    $excludes = @(".venv", ".venv_win", "__pycache__", "dist", "*.build", "tax_vault.json", "installer_output")
    Write-Host "  Excluding: $($excludes -join ', ')"
    Write-Host "  Running robocopy..."
    $robocopyArgs = @($WSL_SRC, $WIN_DEST, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/XD") + $excludes
    & robocopy @robocopyArgs
    if ($LASTEXITCODE -ge 8) {
        Write-Host "[Error] File sync failed (robocopy exit code $LASTEXITCODE)."
        exit 1
    }
    Write-Host "[OK] Files synced to $WIN_DEST"
}

$VENV   = "$WIN_DEST\.venv"
$PYTHON = "$VENV\Scripts\python.exe"
$PIP    = "$VENV\Scripts\pip.exe"

Write-Host ""
Write-Host "  Build dir : $WIN_DEST"
Write-Host "  Venv      : $VENV"
Write-Host "  Python    : $PYTHON"

Set-Location $WIN_DEST
Write-Host "  Working dir set to: $(Get-Location)"

# ── Read version from version.py (single source of truth) ─────────
$versionMatch = Select-String -Path "version.py" -Pattern '__version__\s*=\s*"(.+?)"'
$AppVersion = $versionMatch.Matches.Groups[1].Value
if (-not $AppVersion) { $AppVersion = "dev" }
Write-Host "  Version      : $AppVersion"

# ── Step 1b: Build file preflight ─────────────────────────────────
Write-Host ""
Write-Host "--------------------------------------------------------"
Write-Host "[Step 1b] Build file preflight"
Write-Host "--------------------------------------------------------"

$installerIss = Join-Path $WIN_DEST "scripts\installer.iss"
if (-not (Test-Path $installerIss)) {
    Write-Host "[Error] Missing installer script: $installerIss"
    exit 1
}

$installerText = Get-Content $installerIss -Raw
if ($installerText -match '(?m)^\s*AllowDowngrade\s*=') {
    Write-Host "  Removing unsupported Inno Setup directive: AllowDowngrade"
    $installerText = $installerText -replace '(?m)^\s*AllowDowngrade\s*=.*\r?\n?', ''
    Set-Content -Path $installerIss -Value $installerText -NoNewline
} else {
    Write-Host "  Inno Setup script OK."
}

$zoneIdentifierFiles = Get-ChildItem $WIN_DEST -Recurse -Force -Filter "*:Zone.Identifier" -ErrorAction SilentlyContinue
if ($zoneIdentifierFiles) {
    Write-Host "  Removing Windows Zone.Identifier metadata files..."
    $zoneIdentifierFiles | Remove-Item -Force
} else {
    Write-Host "  No Zone.Identifier metadata files found."
}

# ── Step 2: Create venv ───────────────────────────────────────────
Write-Host ""
Write-Host "--------------------------------------------------------"
Write-Host "[Step 2] Python virtual environment"
Write-Host "--------------------------------------------------------"

if (-not (Test-Path $PYTHON)) {
    Write-Host "  Creating new venv at $VENV ..."
    python -m venv $VENV
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Error] Failed to create virtual environment."
        exit 1
    }
    Write-Host "[OK] Virtual environment created."
} else {
    Write-Host "  Venv already exists at $VENV - skipping creation."
    Write-Host "[OK] Using existing venv."
}

$pyVersion = & $PYTHON --version 2>&1
Write-Host "  Python version: $pyVersion"

# ── Step 3: Install dependencies ─────────────────────────────────
Write-Host ""
Write-Host "--------------------------------------------------------"
Write-Host "[Step 3] Installing dependencies"
Write-Host "--------------------------------------------------------"
Write-Host "  Installing from requirements.txt..."
& $PIP install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Error] pip install failed."
    exit 1
}
Write-Host ""
Write-Host "  Installing build tools (nuitka, ordered-set, zstandard)..."
& $PIP install nuitka ordered-set zstandard
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Error] Failed to install build tools (nuitka)."
    exit 1
}
$nuitkaVersion = & $PYTHON -m nuitka --version 2>&1 | Select-Object -First 1
Write-Host "[OK] Dependencies installed. Nuitka: $nuitkaVersion"

# ── Step 4: Smoke test ────────────────────────────────────────────
Write-Host ""
Write-Host "--------------------------------------------------------"
Write-Host "[Step 4] Smoke test"
Write-Host "--------------------------------------------------------"
Write-Host "  Importing vault and automation modules..."
& $PYTHON -c "from vault import VaultManager; from automation import downloader_26as; print('  imports OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Error] Smoke test failed."
    exit 1
}
Write-Host "[OK] Smoke test passed."

# ── Step 5: Nuitka build ─────────────────────────────────────────
Write-Host ""
Write-Host "--------------------------------------------------------"
Write-Host "[Step 5] Nuitka compilation"
Write-Host "--------------------------------------------------------"
Write-Host "  Compiling app.py to native machine code..."
Write-Host "  Output dir  : dist\"
Write-Host "  Executable  : AayDocCapio.exe"
Write-Host "  This takes 10-20 minutes on first run."
Write-Host ""

& $PYTHON -m nuitka `
    --standalone `
    --windows-console-mode=disable `
    --windows-icon-from-ico=resources\app_icon.ico `
    --output-dir=dist `
    --output-filename=AayDocCapio.exe `
    --include-data-file=assessment_years.json=assessment_years.json `
    --include-data-dir=resources=resources `
    --include-package=automation `
    --include-module=vault `
    --enable-plugin=pyqt6 `
    --assume-yes-for-downloads `
    app.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "[Error] Nuitka compilation failed."
    exit 1
}

if (Test-Path "dist\AayDocCapio") { Remove-Item -Recurse -Force "dist\AayDocCapio" }
Rename-Item "dist\app.dist" "AayDocCapio"
$exeSize = [math]::Round((Get-ChildItem "dist\AayDocCapio" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "[OK] Compiled to dist\AayDocCapio\ (${exeSize} MB total)"

# ── Step 6: Inno Setup ───────────────────────────────────────────
Write-Host ""
Write-Host "--------------------------------------------------------"
Write-Host "[Step 6] Inno Setup installer"
Write-Host "--------------------------------------------------------"

$isccPaths = @(
    "C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
    "C:\Program Files\Inno Setup 7\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Host "  [Warning] Inno Setup not found in standard locations. Skipping."
    Write-Host "  Install from: jrsoftware.org/isdl.php"
} else {
    Write-Host "  Using: $iscc"
    Write-Host "  Building installer..."
    & $iscc /DMyAppVersion="$AppVersion" scripts\installer.iss
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Error] Inno Setup build failed."
        exit 1
    }
    $setupSize = [math]::Round((Get-Item "installer_output\AayDocCapio_Setup_v${AppVersion}.exe").Length / 1MB, 1)
    Write-Host "[OK] Installer created: installer_output\AayDocCapio_Setup_v${AppVersion}.exe (${setupSize} MB)"
}

# ── Step 7: WiX MSI ──────────────────────────────────────────────
Write-Host ""
Write-Host "--------------------------------------------------------"
Write-Host "[Step 7] WiX MSI"
Write-Host "--------------------------------------------------------"

$wix = Get-Command wix -ErrorAction SilentlyContinue
if (-not $wix) {
    Write-Host "  [Warning] WiX not found in PATH. Skipping MSI build."
    Write-Host "  Install with: dotnet tool install --global wix"
} else {
    Write-Host "  WiX found at: $($wix.Source)"
    $wixVer = & wix --version 2>&1
    Write-Host "  WiX version : $wixVer"

    if (-not (Test-Path "installer_output")) { New-Item -ItemType Directory -Path "installer_output" | Out-Null }

    Write-Host "  Accepting OSMF EULA..."
    & wix eula accept wix7

    Write-Host "  Ensuring UI extension is installed..."
    & wix extension add WixToolset.UI.wixext --global 2>$null

    Write-Host "  Building MSI..."
    & wix build scripts\installer.wxs -d Version="$AppVersion" -out installer_output\AayDocCapio_Setup_v${AppVersion}.msi -ext WixToolset.UI.wixext -arch x64
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Error] WiX MSI build failed."
        exit 1
    }
    $msiSize = [math]::Round((Get-Item "installer_output\AayDocCapio_Setup_v${AppVersion}.msi").Length / 1MB, 1)
    Write-Host "[OK] MSI created: installer_output\AayDocCapio_Setup_v${AppVersion}.msi (${msiSize} MB)"
}

# ── Summary ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================================"
Write-Host "  Build complete! $(Get-Date -Format 'HH:mm:ss')"
Write-Host "========================================================"
Write-Host "  Build dir  : $WIN_DEST"
Write-Host "  App folder : dist\AayDocCapio\"
Write-Host "  Installer  : installer_output\AayDocCapio_Setup_v${AppVersion}.exe"
Write-Host "  MSI        : installer_output\AayDocCapio_Setup_v${AppVersion}.msi"
Write-Host "========================================================"
