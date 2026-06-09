# AayDocCapio - Windows Setup & Build Script
# Run from PowerShell on Windows: .\setup_and_build.ps1
#
# Works in two modes:
#   WSL mode    - project lives in WSL; syncs to C:\AayDocCapio-build\ first
#   Windows mode - project already on Windows; builds in place from the project root

$SCRIPT_DIR = $PSScriptRoot
$PROJECT_ROOT_CANDIDATE = Split-Path -Parent $SCRIPT_DIR   # one level up from scripts\

$WSL_SRC  = "\\wsl.localhost\Ubuntu-24.04\home\deepak\projects\AayDocCapio"
$WIN_DEST = "C:\AayDocCapio-build"

Write-Host ""
Write-Host "========================================================"
Write-Host "  AayDocCapio - Setup & Build"
Write-Host "========================================================"

# ── Step 1: Locate / sync project files ──────────────────────────
Write-Host ""

# Detect if project root is a real Windows path (not a symlink into WSL / not a UNC path)
$appPyPath = Join-Path $PROJECT_ROOT_CANDIDATE "app.py"
try { $resolved = (Resolve-Path $PROJECT_ROOT_CANDIDATE -ErrorAction Stop).ProviderPath } catch { $resolved = "" }
$isNativeWindows = ($resolved -match '^[C-Z]:\\') -and ($resolved -notmatch '^\\\\.+')

if ($isNativeWindows -and (Test-Path $appPyPath)) {
    # Real Windows clone - build in place
    $WIN_DEST = $PROJECT_ROOT_CANDIDATE
    Write-Host "[Step 1] Project found at $WIN_DEST - building in place."
} else {
    # Sync from WSL
    Write-Host "[Step 1] Syncing project files from WSL..."

    if (-not (Test-Path $WIN_DEST)) {
        New-Item -ItemType Directory -Path $WIN_DEST | Out-Null
    }

    $excludes = @(".venv", ".venv_win", "__pycache__", "dist", "*.build", "tax_vault.json", "installer_output")
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

Set-Location $WIN_DEST

# ── Step 2: Create venv if it doesn't exist ──────────────────────
if (-not (Test-Path $PYTHON)) {
    Write-Host ""
    Write-Host "[Step 2] Creating Python virtual environment..."
    python -m venv $VENV
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Error] Failed to create virtual environment."
        exit 1
    }
    Write-Host "[OK] Virtual environment created at $VENV"
} else {
    Write-Host ""
    Write-Host "[Step 2] Virtual environment already exists, skipping creation."
}

# ── Step 3: Install dependencies ─────────────────────────────────
Write-Host ""
Write-Host "[Step 3] Installing dependencies..."
& $PIP install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Error] pip install failed."
    exit 1
}
& $PIP install nuitka ordered-set zstandard --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Error] Failed to install build tools (nuitka)."
    exit 1
}
Write-Host "[OK] Dependencies installed."

# ── Step 4: Quick smoke test ──────────────────────────────────────
Write-Host ""
Write-Host "[Step 4] Running smoke test..."
& $PYTHON -c "from vault import VaultManager; from automation import downloader_26as; print('imports OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Error] Smoke test failed. Check output above."
    exit 1
}
Write-Host "[OK] Smoke test passed."

# ── Step 5: Nuitka build ─────────────────────────────────────────
Write-Host ""
Write-Host "[Step 5] Compiling with Nuitka (this takes several minutes)..."
Write-Host "         Python code will be compiled to native machine code."
Write-Host ""

& $PYTHON -m nuitka `
    --standalone `
    --windows-console-mode=disable `
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
Write-Host "[OK] Compiled to dist\AayDocCapio\"

# ── Step 6: Inno Setup ───────────────────────────────────────────
Write-Host ""
Write-Host "[Step 6] Building installer with Inno Setup..."

$isccPaths = @(
    "C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
    "C:\Program Files\Inno Setup 7\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Host "[Warning] Inno Setup not found. Skipping installer."
} else {
    & $iscc scripts\installer.iss
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Error] Inno Setup build failed."
        exit 1
    }
}

# ── Step 7: WiX MSI ──────────────────────────────────────────────
Write-Host ""
Write-Host "[Step 7] Building MSI with WiX..."

$wix = Get-Command wix -ErrorAction SilentlyContinue
if (-not $wix) {
    Write-Host "[Warning] WiX not found in PATH. Skipping MSI build."
    Write-Host "          Install with: dotnet tool install --global wix"
} else {
    if (-not (Test-Path "installer_output")) { New-Item -ItemType Directory -Path "installer_output" | Out-Null }
    # Accept OSMF EULA required by WiX v7 (WIX7015); no-op if already accepted
    & wix eula accept wix7
    # Install UI extension if not already present (no-op if installed)
    & wix extension add WixToolset.UI.wixext --global 2>$null
    & wix build scripts\installer.wxs -out installer_output\AayDocCapio.msi -ext WixToolset.UI.wixext
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Error] WiX MSI build failed."
        exit 1
    }
    Write-Host "[OK] MSI created: installer_output\AayDocCapio.msi"
}

Write-Host ""
Write-Host "========================================================"
Write-Host "  Build complete!"
Write-Host "  App folder : dist\AayDocCapio\"
Write-Host "  Installer  : installer_output\AayDocCapio_Setup_v1.0.0.exe"
Write-Host "  MSI        : installer_output\AayDocCapio.msi"
Write-Host "========================================================"
