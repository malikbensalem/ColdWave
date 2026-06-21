@echo off
REM ColdWave - easy local startup for Windows (backend + frontend)
REM Usage: double-click start.bat  OR  run "start.bat" in a terminal.
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo [coldwave] Validating prerequisites...
where python >nul 2>&1 || (echo [error] Python 3.11+ not found. Install from https://python.org and re-run. & pause & exit /b 1)
where node   >nul 2>&1 || (echo [error] Node 18+ not found. Install from https://nodejs.org and re-run. & pause & exit /b 1)
where yarn   >nul 2>&1 || (echo [error] yarn not found. Run: npm install -g yarn & pause & exit /b 1)

if not exist "backend\.env"  (echo [error] Missing backend\.env. Copy backend\.env.example to backend\.env and fill it in. & pause & exit /b 1)
if not exist "frontend\.env" (echo [error] Missing frontend\.env. Copy frontend\.env.example to frontend\.env and fill it in. & pause & exit /b 1)

echo [coldwave] Checking MongoDB reachability...
for /f "usebackq tokens=1,* delims==" %%a in ("backend\.env") do (
  if "%%a"=="MONGO_URL" set "MONGO_URL=%%b"
)
set MONGO_URL=%MONGO_URL:"=%
python -c "from pymongo import MongoClient; MongoClient('%MONGO_URL%', serverSelectionTimeoutMS=2500).admin.command('ping')" 2>nul || (echo [error] Cannot reach MongoDB at %MONGO_URL%. Start MongoDB ^(mongod / Docker / Atlas^) and retry. & pause & exit /b 1)

if not exist "frontend\node_modules" (
  echo [coldwave] Installing frontend dependencies ^(first run^)...
  pushd frontend & call yarn install & popd
)
echo [coldwave] Ensuring backend dependencies...
python -m pip install -q -r backend\requirements.txt

echo.
echo ========================================
echo   ColdWave starting
echo   Backend  : http://localhost:8001/api/
echo   Frontend : http://localhost:3000
echo   Health   : http://localhost:8001/api/health
echo   Close the two opened windows to stop.
echo ========================================
echo.

start "ColdWave Backend"  cmd /k "cd /d %~dp0backend && uvicorn server:app --host 0.0.0.0 --port 8001"
start "ColdWave Frontend" cmd /k "cd /d %~dp0frontend && yarn start"

echo [coldwave] Two windows opened (backend + frontend). This window can be closed.
endlocal
