@echo off
setlocal
title ManaCam Launcher

set "DIR=%~dp0"
set "DIR=%DIR:~0,-1%"
cd /d "%DIR%"

wt -w 0 new-tab --title "Webapp" -d "%DIR%" cmd /k python -m uvicorn webapp:app --port 8005 --reload ^; new-tab --title "Cloudflared" -d "%DIR%" cmd /k cloudflared tunnel --url http://localhost:8005

echo ===================================================
echo   ManaCam launched in Windows Terminal tabs.
echo   Check the "Cloudflared" tab for the public URL.
echo   Do NOT close the tabs.
echo ===================================================
echo.
pause
endlocal
