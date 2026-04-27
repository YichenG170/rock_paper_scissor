@echo off
setlocal

set "RPS_ROOT=%~dp0"
set "RPS_APP=%RPS_ROOT%web\app.py"
set "RPS_URL=http://127.0.0.1:8001/"

echo Cleaning old rock-paper-scissors server processes on ports 8001 and 5555...
for %%P in (8001 5555) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
    if not "%%A"=="0" (
      echo Stopping PID %%A on port %%P
      taskkill /PID %%A /F >nul 2>nul
    )
  )
)

echo Starting web server...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = $env:RPS_ROOT; " ^
  "$app = $env:RPS_APP; " ^
  "$out = Join-Path $root 'web\server.out.log'; " ^
  "$err = Join-Path $root 'web\server.err.log'; " ^
  "Start-Process -FilePath python -ArgumentList @($app) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2"

echo Opening %RPS_URL%
start "" "%RPS_URL%"

endlocal
