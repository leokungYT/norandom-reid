@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo      Auto Update: norandom-reid Bot
echo ============================================
echo Folder: %CD%
echo.

:: Kill ADB and Python processes to prevent file locks
echo [PRE] Stopping ADB and Bot processes...
taskkill /f /im adb.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1
ping -n 3 127.0.0.1 >nul

set "REPO_URL=https://github.com/leokungYT/norandom-reid/archive/refs/heads/main.zip"
set "ZIP_NAME=norandom_update.zip"
set "EXTRACT_DIR=update_temp"

:: 1. Download the latest version (retry up to 3 times with curl, then fallback to PowerShell)
echo [1/5] Downloading latest version from GitHub...
set "DOWNLOAD_OK=0"

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
            ping -n 4 127.0.0.1 >nul
        )
    )
)

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

:: 4. Copy new files (exclude THIS running .bat so it is never overwritten mid-run)
echo [4/5] Copying new files...
echo ============================================
if exist "%SOURCE_FOLDER%\backup" rd /s /q "%SOURCE_FOLDER%\backup"
if exist "%SOURCE_FOLDER%\backup-id" rd /s /q "%SOURCE_FOLDER%\backup-id"
if exist "%SOURCE_FOLDER%\test-ocr-output" rd /s /q "%SOURCE_FOLDER%\test-ocr-output"

> "_nr_exclude.txt" echo autoupdate.bat
xcopy /s /e /y /EXCLUDE:_nr_exclude.txt "%SOURCE_FOLDER%\*" ".\"
del /q "_nr_exclude.txt" >nul 2>&1

:: If the repo shipped a newer autoupdate.bat, stage it (avoid overwriting the running one)
if exist "%SOURCE_FOLDER%\autoupdate.bat" (
    fc /b "%SOURCE_FOLDER%\autoupdate.bat" "autoupdate.bat" >nul 2>&1
    if errorlevel 1 (
        copy /y "%SOURCE_FOLDER%\autoupdate.bat" "autoupdate_new.bat" >nul
        echo [NOTE] autoupdate.bat changed - saved as autoupdate_new.bat ^(replace it before next update^)
    )
)
echo ============================================

:: 5. Cleanup
echo [5/5] Cleaning up temporary files...
del /q "%ZIP_NAME%" >nul 2>&1
for /L %%i in (1,1,5) do (
    if exist "%EXTRACT_DIR%" (
        rd /s /q "%EXTRACT_DIR%" >nul 2>&1
        if exist "%EXTRACT_DIR%" ping -n 3 127.0.0.1 >nul
    )
)

echo [PIP] Checking required Python packages...
py -m pip install --quiet pure-python-adb opencv-python numpy psutil pytesseract pyperclip >nul 2>&1

echo.
echo ============================================
echo      Update Successful!  (Folder: %CD%)
echo ============================================
echo.
pause
