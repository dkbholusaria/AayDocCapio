@echo off
echo ========================================================
echo   Tax Downloader - Windows Packaging Script (PyInstaller)
echo ========================================================
echo.

:: Check for python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python is not installed or not in PATH.
    echo Please install Python 3.8+ and try again.
    pause
    exit /b 1
)

:: Check for pyinstaller
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [Info] PyInstaller is missing. Installing PyInstaller...
    pip install pyinstaller
)

:: Check dependencies from requirements.txt
echo [Info] Verifying project dependencies...
pip install -r requirements.txt

echo.
echo [Info] Starting executable compilation...
echo [Info] Packaging app.py into a single-file console-less executable...
echo.

pyinstaller --onefile --noconsole --name="TaxDownloader" --clean app.py

if %errorlevel% eq 0 (
    echo.
    echo ========================================================
    echo   [Success] TaxDownloader.exe compiled successfully!
    echo   The executable is located in the 'dist' folder.
    echo ========================================================
) else (
    echo.
    echo [Error] PyInstaller compilation failed. See errors above.
)

pause
