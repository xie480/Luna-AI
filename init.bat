@echo off
echo ==========================================
echo       Luna-AI Init Script (Windows)
echo ==========================================
echo.

echo [1/3] Initializing Go Backend...
cd backend\runtime
go mod tidy
cd ..\..
echo Go initialization complete.
echo.

echo [2/3] Initializing Python AI Service...
cd backend\ai-service
pip install -e ".[dev]"
cd ..\..
echo Python initialization complete.
echo.

echo [3/3] Initializing Frontend...
cd frontend
call npm install
cd ..
echo Frontend initialization complete.
echo.

echo ==========================================
echo All dependencies initialized! You can now run start.bat
echo ==========================================
pause
