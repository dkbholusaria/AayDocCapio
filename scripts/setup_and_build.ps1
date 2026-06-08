# AayDocCapio - Windows Setup & Build Script
# Run from PowerShell on Windows: .\setup_and_build.ps1
# This script syncs the project from WSL, sets up venv, and builds the exe.

$WSL_SRC  = "\\wsl.localhost\Ubuntu-24.04\home\deepak\projects\AayDocCapio"
$WIN_DEST = "C:\ITD-build"
$VENV     = "$WIN_DEST\.venv"
$PYTHON   = "$VENV\Scripts\python.exe"
$PIP      = "$VENV\Scripts\pip.exe"

Write-Host ""
Write-Host "========================================================"
Write-Host "  AayDocCapio - Setup & Build"
Write-Host "========================================================"

# ── Step 1: Sync project files from WSL ──────────────────────────
Write-Host ""
Write-Host "[Step 1] Syncing project files from WSL..."

$excludes = @(".venv", ".venv_win", "__pycache__", "dist", "*.build", "tax_vault.json", "installer_output")

if (-not (Test-Path $WIN_DEST)) {
    New-Item -ItemType Directory -Path $WIN_DEST | Out-Null
}

# Robocopy: sync WSL source to Windows destination
$robocopyExcludes = $excludes | ForEach-Object { "/XD $_" }
$robocopyArgs = @($WSL_SRC, $WIN_DEST, "/E", "/NFL", "/NDL", "/NJH", "/NJS") + $robocopyExcludes
$result = & robocopy @robocopyArgs
if ($LASTEXITCODE -ge 8) {
    Write-Host "[Error] File sync failed (robocopy exit code $LASTEXITCODE)."
    exit 1
}
Write-Host "[OK] Files synced to $WIN_DEST"

# ── Step 2: Create venv if it doesn't exist ──────────────────────
Set-Location $WIN_DEST

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
    --include-package=vault `
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
    Write-Host "[Done] App folder: dist\AayDocCapio\"
    exit 0
}

& $iscc scripts\installer.iss
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Error] Inno Setup build failed."
    exit 1
}

Write-Host ""
Write-Host "========================================================"
Write-Host "  Build complete!"
Write-Host "  App folder : dist\AayDocCapio\"
Write-Host "  Installer  : installer_output\AayDocCapio_Setup_v1.0.0.exe"
Write-Host "========================================================"
