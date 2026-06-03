@echo off
echo ========================================================
echo   ITD Docs Downloader - Windows Build Script (Nuitka)
echo ========================================================
echo.

:: ── Change to project root (one level up from scripts\) ───
cd /d "%~dp0.."

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

:: ── Nuitka — compile to native C executable ──────────────
echo.
echo [Step 2/3] Compiling with Nuitka (this takes several minutes)...
echo            Python code will be compiled to native machine code.
echo.

python -m nuitka ^
    --standalone ^
    --windows-console-mode=disable ^
    --output-dir=dist ^
    --output-filename=TaxDownloader.exe ^
    --include-data-file=assessment_years.json=assessment_years.json ^
    --include-data-dir=resources=resources ^
    --include-package=automation ^
    --include-package=vault ^
    --enable-plugin=pyqt6 ^
    --assume-yes-for-downloads ^
    app.py

if %errorlevel% neq 0 (
    echo [Error] Nuitka compilation failed. See errors above.
    pause & exit /b 1
)
echo [OK] dist\app.dist\ folder created.

:: ── Rename output folder to TaxDownloader ────────────────
if exist "dist\TaxDownloader" rmdir /s /q "dist\TaxDownloader"
rename "dist\app.dist" "TaxDownloader"
echo [OK] Renamed to dist\TaxDownloader\

:: ── Inno Setup — build the installer ─────────────────────
echo.
echo [Step 3/3] Building installer with Inno Setup...

set ISCC=""
if exist "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
if exist "C:\Program Files\Inno Setup 7\ISCC.exe"       set ISCC="C:\Program Files\Inno Setup 7\ISCC.exe"
if %ISCC%=="" if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if %ISCC%=="" if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if %ISCC%=="" (
    echo [Warning] Inno Setup not found. Skipping installer build.
    echo           Download from https://jrsoftware.org/isdl.php and re-run.
    echo.
    echo [Done] App folder only: dist\TaxDownloader\
    pause & exit /b 0
)

%ISCC% scripts\installer.iss
if %errorlevel% neq 0 (
    echo [Error] Inno Setup build failed.
    pause & exit /b 1
)

echo.
echo ========================================================
echo   Build complete!
echo   App folder : dist\TaxDownloader\
echo   Installer  : installer_output\ITDDocsDownloader_Setup_v1.0.0.exe
echo ========================================================
pause
