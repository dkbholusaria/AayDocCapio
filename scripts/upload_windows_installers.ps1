# upload_windows_installers.ps1
# Run this on Windows after building locally with build_win.bat (or after
# downloading the CI build artifacts), to upload the installers to the
# existing GitHub Release for the current version.
#
# Usage (from project root):
#   powershell -ExecutionPolicy Bypass -File scripts\upload_windows_installers.ps1
#
# Requirements: gh (GitHub CLI) authenticated, files in installer_output\

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Read version ──────────────────────────────────────────────────────────────
$VERSION = python -c "from version import __version__; print(__version__)"
$TAG     = "v$VERSION"

Write-Host ""
Write-Host "Uploading Windows installers for $TAG ..." -ForegroundColor Cyan

# ── Expected file paths ───────────────────────────────────────────────────────
$EXE = "installer_output\AayDocCapio_Setup_v$VERSION.exe"
$MSI = "installer_output\AayDocCapio_Setup_v$VERSION.msi"

foreach ($f in @($EXE, $MSI)) {
    if (-not (Test-Path $f)) {
        Write-Host "  ERROR: $f not found. Run build_win.bat first." -ForegroundColor Red
        exit 1
    }
    $size = (Get-Item $f).Length / 1MB
    Write-Host "  Found: $f  ($([math]::Round($size,1)) MB)"
}

# ── Upload ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Uploading to GitHub Release $TAG ..."

gh release upload $TAG $EXE $MSI --clobber --repo dkbholusaria/AayDocCapio

Write-Host ""
Write-Host "Done! Installers attached to:" -ForegroundColor Green
Write-Host "  https://github.com/dkbholusaria/AayDocCapio/releases/tag/$TAG"
Write-Host ""
