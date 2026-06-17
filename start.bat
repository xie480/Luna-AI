@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo       Luna-AI Start Script (Windows)
echo ==========================================
echo.

set "TTS_BAT_PATH="
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if "%%a"=="TTS_BAT_PATH" set "TTS_BAT_PATH=%%b"
)

REM 解析 frontend/src/renderer/stores/systemStore.ts 或者干脆通过 localstorage db，
REM 但由于 localstorage 存在于浏览器中，bat 脚本无法直接读取。
REM 所以我们将 TTS 开关状态依赖于 TTS_BAT_PATH 是否存在。
REM 如果用户在前端关闭了 TTS，他们不会收到音频；bat 启动的服务只是在那挂载。
REM 若要强行通过脚本关闭，用户需修改 .env。这里保持不变，仅在前端关闭调用。

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
