@echo off
echo Starting ngrok tunnel...
echo.
cd /d "c:\Users\JyothiG\OneDrive - gradientm.com\auto mial\ngrok-v3-stable-windows-amd64"
ngrok.exe http 5000 --request-header-add="ngrok-skip-browser-warning:true"
pause