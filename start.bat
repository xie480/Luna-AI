@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo       Luna-AI Start Script (Windows)
echo ==========================================
echo.

:: 读取 .env 文件获取 TTS_BAT_PATH
set "TTS_BAT_PATH="
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%a in (.env) do (
        if "%%a"=="TTS_BAT_PATH" (
            set "TTS_BAT_PATH=%%b"
        )
    )
)

:: 清理可能的回车符或空格
if defined TTS_BAT_PATH (
    for /f "tokens=* delims= " %%a in ("!TTS_BAT_PATH!") do set "TTS_BAT_PATH=%%a"
)

if defined TTS_BAT_PATH (
    if not "!TTS_BAT_PATH!"=="" (
        echo [1/3] Starting TTS Service...
        for %%I in ("!TTS_BAT_PATH!") do set "TTS_DIR=%%~dpI"
        start "Luna-AI TTS Service" cmd /k "cd /d "!TTS_DIR!" && "!TTS_BAT_PATH!""
        
        echo [2/3] Starting Python AI Service (with Memory Guardian embedded)...
        start "Luna-AI Python Service" cmd /k "cd backend\ai-service && uvicorn app.main:app --reload --host 0.0.0.0 --port 8088"
        
        echo [3/3] Starting Frontend (Electron Desktop)...
        start "Luna-AI Frontend" cmd /k "cd frontend && npm run dev"
        goto :end_start
    )
)

echo [1/2] Starting Python AI Service (with Memory Guardian embedded)...
start "Luna-AI Python Service" cmd /k "cd backend\ai-service && uvicorn app.main:app --reload --host 0.0.0.0 --port 8088"

echo [2/2] Starting Frontend (Electron Desktop)...
start "Luna-AI Frontend" cmd /k "cd frontend && npm run dev"

:end_start
echo.
echo All services started in separate windows!
echo Please check the new command prompt windows for logs.
echo.
pause
