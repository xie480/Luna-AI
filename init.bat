@echo off
echo ==========================================
echo       Luna-AI Init Script (Windows)
echo ==========================================
echo.

echo [1/2] Initializing Python AI Service...
cd backend\ai-service
pip install -e ".[dev]"
cd ..\..
echo Python initialization complete.
echo.

echo [2/2] Initializing Frontend...
cd frontend
call npm install
cd ..
echo Frontend initialization complete.
echo.

echo ==========================================
echo All dependencies initialized! You can now run start.bat
echo ==========================================
pause
