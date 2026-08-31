@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   Cloudflare WARP + norandom-reid Bot
echo ============================================

set "WARP_DIR=%ProgramFiles%\Cloudflare\Cloudflare WARP"
set "WARP_CLI=%WARP_DIR%\warp-cli.exe"
if not exist "%WARP_CLI%" (
    set "WARP_DIR=%ProgramFiles(x86)%\Cloudflare\Cloudflare WARP"
    set "WARP_CLI=!WARP_DIR!\warp-cli.exe"
)

:: --- ถ้ายังไม่ติดตั้ง WARP -> ติดตั้งให้ ---
if not exist "!WARP_CLI!" (
    echo [WARP] ยังไม่ได้ติดตั้ง - กำลังติดตั้งผ่าน winget...
    winget install --id Cloudflare.Warp -e --accept-package-agreements --accept-source-agreements
    set "WARP_DIR=%ProgramFiles%\Cloudflare\Cloudflare WARP"
    set "WARP_CLI=!WARP_DIR!\warp-cli.exe"
)
if not exist "!WARP_CLI!" (
    echo [WARP] winget ไม่ได้ผล - โหลดตัวติดตั้งมาลงเอง...
    curl -k -L -o "%TEMP%\warp_installer.msi" "https://1111-releases.cloudflareclient.com/win/latest"
    msiexec /i "%TEMP%\warp_installer.msi" /qn /norestart
    ping -n 20 127.0.0.1 >nul
    set "WARP_DIR=%ProgramFiles%\Cloudflare\Cloudflare WARP"
    set "WARP_CLI=!WARP_DIR!\warp-cli.exe"
)

:: --- เปิด GUI + สั่งเชื่อมต่อ ---
if exist "!WARP_CLI!" (
    echo [WARP] เปิดโปรแกรม Cloudflare WARP...
    start "" "!WARP_DIR!\Cloudflare WARP.exe"
    ping -n 4 127.0.0.1 >nul
    echo [WARP] กำลังเชื่อมต่อ...
    "!WARP_CLI!" --accept-tos connect
    :: รอจนขึ้น Connected (สูงสุด ~45 วิ)
    set "WARP_OK=0"
    for /L %%i in (1,1,15) do (
        if !WARP_OK! EQU 0 (
            "!WARP_CLI!" status 2>nul | findstr /i "Connected" >nul && (
                set "WARP_OK=1"
                echo [WARP] เชื่อมต่อสำเร็จ!
            )
            if !WARP_OK! EQU 0 ping -n 4 127.0.0.1 >nul
        )
    )
    if !WARP_OK! EQU 0 echo [WARP] ยังไม่ Connected แต่จะรันบอทต่อ...
) else (
    echo [WARP] ติดตั้ง WARP ไม่สำเร็จ - รันบอทต่อโดยไม่มี VPN
)

echo.
echo [BOT] เริ่มรันบอท...
adb disconnect 127.0.0.1:16494 >nul 2>&1
py main.py
