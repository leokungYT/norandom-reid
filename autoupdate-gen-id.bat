@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Auto Update Bot (norandom-reid)
echo ============================================
echo.

echo [1/2] Pulling latest code from GitHub...
git pull origin main
if errorlevel 1 (
    echo.
    echo !!! Update FAILED - check internet/git then try again !!!
    pause
    exit /b 1
)

echo.
echo [2/2] Checking required Python packages...
py -m pip install --quiet pure-python-adb opencv-python numpy psutil pytesseract pyperclip

echo.
echo ============================================
echo   Update complete! Run run.bat to start.
echo ============================================
pause
