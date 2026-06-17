@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo       Luna-AI Start Script (Windows)
echo ==========================================
echo.

set "TTS_BAT_PATH="
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if "%%a"=="TTS_BAT_PATH" set "TTS_BAT_PATH=%%b"
    )
)

REM Parse frontend/src/renderer/stores/systemStore.ts or via localstorage db.
REM However, since localstorage is in the browser, the bat script cannot read it directly.
REM So we rely on TTS_BAT_PATH existence for TTS toggle.
REM If the user turned off TTS in frontend, they won't receive audio; the bat service just mounts.
REM To force disable via script, user should modify .env. Keeping it as is here.

if defined TTS_BAT_PATH (
    echo [1/3] Starting TTS Service...
    for %%I in ("!TTS_BAT_PATH!") do set "TTS_DIR=%%~dpI"
    start "Luna-AI TTS Service" /D "!TTS_DIR!" cmd /k "!TTS_BAT_PATH!"
    echo [2/3] Starting Python AI Service...
    set "PY_DIR=%~dp0backend\ai-service"
    start "Luna-AI Python Service" /D "!PY_DIR!" cmd /k "uvicorn app.main:app --reload --host 0.0.0.0 --port 8088"
    echo [3/3] Starting Frontend...
    set "FE_DIR=%~dp0frontend"
    start "Luna-AI Frontend" /D "!FE_DIR!" cmd /k "npm run dev"
    goto :end_start
)

echo [1/2] Starting Python AI Service...
set "PY_DIR=%~dp0backend\ai-service"
start "Luna-AI Python Service" /D "!PY_DIR!" cmd /k "uvicorn app.main:app --reload --host 0.0.0.0 --port 8088"

echo [2/2] Starting Frontend...
set "FE_DIR=%~dp0frontend"
start "Luna-AI Frontend" /D "!FE_DIR!" cmd /k "npm run dev"

:end_start
echo.
echo All services started in separate windows!
echo Please check the new command prompt windows for logs.
echo.
pause
