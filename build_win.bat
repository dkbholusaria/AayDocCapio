@echo off
echo ========================================================
echo   ITD Docs Downloader - Windows Build Script
echo ========================================================
echo.

:: ── Check Python ─────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python is not installed or not in PATH.
    pause & exit /b 1
)

:: ── Install / verify dependencies ────────────────────────
echo [Step 1/3] Installing dependencies...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [Error] pip install failed.
    pause & exit /b 1
)

:: ── PyInstaller — build the exe ──────────────────────────
echo.
echo [Step 2/3] Building TaxDownloader.exe with PyInstaller...
pyinstaller --onefile --noconsole --name="TaxDownloader" --clean ^
    --add-data "assessment_years.json;." ^
    --add-data "resources;resources" ^
    --add-data "automation;automation" ^
    app.py

if %errorlevel% neq 0 (
    echo [Error] PyInstaller build failed. See errors above.
    pause & exit /b 1
)
echo [OK] dist\TaxDownloader.exe created.

:: ── Inno Setup — build the installer ────────────────────
echo.
echo [Step 3/3] Building installer with Inno Setup...

:: Try default Inno Setup install locations (7 preferred, fallback to 6)
set ISCC=""
if exist "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
if exist "C:\Program Files\Inno Setup 7\ISCC.exe"       set ISCC="C:\Program Files\Inno Setup 7\ISCC.exe"
if %ISCC%=="" if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if %ISCC%=="" if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if %ISCC%=="" (
    echo [Warning] Inno Setup not found. Skipping installer build.
    echo           Download from https://jrsoftware.org/isdl.php and re-run.
    echo.
    echo [Done] Executable only: dist\TaxDownloader.exe
    pause & exit /b 0
)

%ISCC% installer.iss
if %errorlevel% neq 0 (
    echo [Error] Inno Setup build failed.
    pause & exit /b 1
)

echo.
echo ========================================================
echo   Build complete!
echo   Executable : dist\TaxDownloader.exe
echo   Installer  : installer_output\ITDDocsDownloader_Setup_v1.0.0.exe
echo ========================================================
pause
