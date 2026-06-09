#!/bin/bash
# Exit immediately if any command exits with a non-zero status
set -e

# Change directory to the project root (one level up from scripts)
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "========================================================"
echo "   Tax Downloader - Python Virtual Environment Setup    "
echo "========================================================"
echo

# 1. Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "[+] Creating virtual environment (.venv)..."
    python3 -m venv .venv
else
    echo "[*] Virtual environment (.venv) already exists."
fi

# 2. Activate virtual environment
echo "[+] Activating virtual environment..."
source .venv/bin/activate

# 3. Upgrade pip
echo "[+] Upgrading pip..."
pip install --upgrade pip

# 4. Install dependencies
if [ -f "requirements.txt" ]; then
    echo "[+] Installing dependencies from requirements.txt..."
    pip install -r requirements.txt
else
    echo "[-] Error: requirements.txt not found!"
    exit 1
fi

# 5. Install Playwright browser binaries
echo "[+] Installing Playwright Chromium browser..."
playwright install chromium

echo
echo "========================================================"
echo "   Setup Completed Successfully!                        "
echo "========================================================"
echo "To run the application, execute these commands:"
echo "  source .venv/bin/activate"
echo "  python app.py"
echo "========================================================"
