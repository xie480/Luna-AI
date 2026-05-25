@echo off
echo ==========================================
echo       Luna-AI Start Script (Windows)
echo ==========================================
echo.

echo [1/3] Starting Go Backend...
start "Luna-AI Go Backend" cmd /k "cd backend\runtime && go run ./cmd/main.go"

echo [2/3] Starting Python AI Service...
start "Luna-AI Python Service" cmd /k "cd backend\ai-service && python -m app.main"

echo [3/3] Starting Frontend (Electron Desktop)...
start "Luna-AI Frontend" cmd /k "cd frontend && set ELECTRON_RUN_AS_NODE=&& npm run dev"

echo.
echo All services started in separate windows!
echo Please check the new command prompt windows for logs.
echo.
pause
