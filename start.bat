@echo off
echo ==========================================
echo       Luna-AI Start Script (Windows)
echo ==========================================
echo.

echo [1/2] Starting Python AI Service...
start "Luna-AI Python Service" cmd /k "cd backend\ai-service && python -m app.main"

echo [2/2] Starting Frontend (Electron Desktop)...
start "Luna-AI Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo All services started in separate windows!
echo Please check the new command prompt windows for logs.
echo.
pause