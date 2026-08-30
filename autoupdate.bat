@echo off
setlocal enabledelayedexpansion

:: =========================================================
:: Auto Update Script for norandom-reid Bot (in-place update)
:: =========================================================
:: URL: https://github.com/leokungYT/norandom-reid
:: =========================================================

:: Re-launch a copy of this .bat from TEMP so the update can safely
:: overwrite autoupdate.bat itself in the bot folder.
if /i not "%~dp0"=="%TEMP%\" (
    copy /y "%~f0" "%TEMP%\norandom_autoupdate.bat" >nul
    start "norandom-reid Auto Update" "%TEMP%\norandom_autoupdate.bat" "%~dp0"
    exit
)

set "TARGET_FOLDER=%~1"
if "%TARGET_FOLDER:~-1%"=="\" set "TARGET_FOLDER=%TARGET_FOLDER:~0,-1%"
cd /d "%TARGET_FOLDER%"

echo.
echo ============================================
echo      Auto Update: norandom-reid Bot
echo ============================================
echo Target: %TARGET_FOLDER%
echo.

:: Kill ADB and Python processes to prevent file locks
echo [PRE] Stopping ADB and Bot processes...
taskkill /f /im adb.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1
timeout /t 2 /nobreak >nul

set "REPO_URL=https://github.com/leokungYT/norandom-reid/archive/refs/heads/main.zip"
set "ZIP_NAME=norandom_update.zip"
set "EXTRACT_DIR=update_temp"

:: 1. Download the latest version (retry up to 3 times with curl, then fallback to PowerShell)
echo [1/5] Downloading latest version from GitHub...

set "DOWNLOAD_OK=0"

:: Try curl with retries
for /L %%i in (1,1,3) do (
    if !DOWNLOAD_OK! EQU 0 (
        echo [CURL] Attempt %%i/3...
        curl -k -L --retry 2 --retry-delay 3 --connect-timeout 15 "%REPO_URL%" -o "%ZIP_NAME%" >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            if exist "%ZIP_NAME%" (
                set "DOWNLOAD_OK=1"
                echo [CURL] Download successful
            )
        ) else (
            echo [CURL] Attempt %%i failed, retrying...
            timeout /t 3 /nobreak >nul
        )
    )
)

:: Fallback to PowerShell if curl failed
if !DOWNLOAD_OK! EQU 0 (
    echo [CURL] All attempts failed. Trying PowerShell fallback...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%REPO_URL%' -OutFile '%ZIP_NAME%' -UseBasicParsing -TimeoutSec 60; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"
    if !ERRORLEVEL! EQU 0 (
        if exist "%ZIP_NAME%" (
            set "DOWNLOAD_OK=1"
            echo [PS] Download successful via PowerShell
        )
    )
)

if !DOWNLOAD_OK! EQU 0 (
    echo.
    echo [ERROR] Download failed. Please check your internet connection.
    echo [TIP] Try: ipconfig /flushdns   then run this script again.
    pause
    exit /b 1
)

:: 2. Extract files
echo [2/5] Extracting files...
if exist "%EXTRACT_DIR%" rd /s /q "%EXTRACT_DIR%"
powershell -Command "Expand-Archive -Path '%ZIP_NAME%' -DestinationPath '%EXTRACT_DIR%' -Force"

:: Identify the source directory (GitHub zips name folders like 'norandom-reid-main')
set "SOURCE_FOLDER="
for /d %%f in ("%EXTRACT_DIR%\*") do set "SOURCE_FOLDER=%%f"

if not defined SOURCE_FOLDER (
    echo.
    echo [ERROR] Extraction failed. ZIP might be corrupt or the repo is private.
    del /q "%ZIP_NAME%" >nul 2>&1
    pause
    exit /b 1
)

:: 3. Cleanup old img folder
echo [3/5] Cleaning old img folder (if needed)...
if exist "img" rd /s /q "img"

:: 4. Secure local backups + Copy new files from extracted zip
echo [4/5] Copying new files to %TARGET_FOLDER%\...
echo ============================================
:: ลบโฟลเดอร์ backup/ผลเทสจากไฟล์ที่โหลดมาก่อน กันเขียนทับของเครื่องนี้
if exist "%SOURCE_FOLDER%\backup" rd /s /q "%SOURCE_FOLDER%\backup"
if exist "%SOURCE_FOLDER%\backup-id" rd /s /q "%SOURCE_FOLDER%\backup-id"
if exist "%SOURCE_FOLDER%\test-ocr-output" rd /s /q "%SOURCE_FOLDER%\test-ocr-output"

xcopy /s /e /y "%SOURCE_FOLDER%\*" "%TARGET_FOLDER%\"
echo ============================================

:: 5. Cleanup
echo [5/5] Cleaning up temporary files...
del /q "%ZIP_NAME%"
:: retry a few times - Windows Defender may still hold freshly extracted files
for /L %%i in (1,1,5) do (
    if exist "%EXTRACT_DIR%" (
        rd /s /q "%EXTRACT_DIR%" >nul 2>&1
        if exist "%EXTRACT_DIR%" timeout /t 2 /nobreak >nul
    )
)

:: Make sure required Python packages are installed (bot needs OCR etc.)
echo [PIP] Checking required Python packages...
py -m pip install --quiet pure-python-adb opencv-python numpy psutil pytesseract pyperclip >nul 2>&1

echo.
echo ============================================
echo      Update Successful (Saved in %TARGET_FOLDER%)
echo ============================================
echo.
pause
