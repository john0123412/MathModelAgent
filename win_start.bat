@echo off
chcp 65001 >nul 2>&1
echo =============================================
echo  MathModelAgent Launcher
echo  Redis(Docker) + Backend(8003) + Frontend(5173)
echo =============================================
echo.

:: ====================== Kill old processes ======================
echo [0/4] Cleaning up old processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8002" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8003" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 /nobreak >nul 2>&1
echo Cleanup done.
echo.

:: ====================== Check Docker ======================
echo [1/4] Checking Docker Desktop...
docker info >nul 2>&1
if %errorlevel% neq 0 goto start_docker
goto docker_ok

:start_docker
echo Docker not running. Starting Docker Desktop...
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
echo Waiting for Docker (up to 120s)...
set /a count=0

:wait_docker_loop
timeout /t 5 /nobreak >nul 2>&1
docker info >nul 2>&1
if %errorlevel% equ 0 goto docker_ok
set /a count+=1
if %count% geq 24 goto docker_fail
echo   Waiting... %count%/24
goto wait_docker_loop

:docker_fail
echo.
echo ERROR: Docker startup timeout.
pause
exit /b 1

:docker_ok
echo Docker is ready.
echo.

:: ====================== Start Redis ======================
echo [2/4] Starting Redis...
docker ps -a --format "{{.Names}}" 2>nul | findstr "redis-mma" >nul 2>&1
if %errorlevel% equ 0 (
    docker start redis-mma >nul 2>&1
    echo Redis container started.
) else (
    echo Creating Redis container...
    docker run -d --name redis-mma -p 6379:6379 --restart unless-stopped redis:latest >nul 2>&1
    echo Redis container created.
)
timeout /t 2 /nobreak >nul 2>&1
docker exec redis-mma redis-cli ping >nul 2>&1
if %errorlevel% neq 0 goto redis_fail
echo Redis OK.
echo.
goto redis_ok

:redis_fail
echo.
echo ERROR: Redis not responding.
pause
exit /b 1

:redis_ok

:: ====================== Start Backend ======================
echo [3/4] Starting backend on port 8003...

:: Write backend start script
echo @echo off > "%TEMP%\mma_backend.bat"
echo cd /d D:\workspace\MathModelAgent\backend >> "%TEMP%\mma_backend.bat"
echo D:\workspace\MathModelAgent\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir D:\workspace\MathModelAgent\backend --host 0.0.0.0 --port 8003 --reload >> "%TEMP%\mma_backend.bat"
echo pause >> "%TEMP%\mma_backend.bat"

start "MMA-Backend" cmd /k "%TEMP%\mma_backend.bat"
echo Backend window opened.
timeout /t 5 /nobreak >nul 2>&1

:: ====================== Start Frontend ======================
echo [4/4] Starting frontend on port 5173...

:: Write frontend start script
echo @echo off > "%TEMP%\mma_frontend.bat"
echo cd /d D:\workspace\MathModelAgent\frontend >> "%TEMP%\mma_frontend.bat"
echo pnpm run dev >> "%TEMP%\mma_frontend.bat"
echo pause >> "%TEMP%\mma_frontend.bat"

start "MMA-Frontend" cmd /k "%TEMP%\mma_frontend.bat"
echo Frontend window opened.
timeout /t 5 /nobreak >nul 2>&1

:: ====================== Done ======================
echo.
echo =============================================
echo  All services started!
echo  Frontend: http://localhost:5173
echo  Backend:  http://localhost:8003
echo  Redis:    localhost:6379
echo =============================================
echo.
echo Opening browser in 3 seconds...
timeout /t 3 /nobreak >nul 2>&1
start http://localhost:5173 2>nul
echo.
echo Done. This window can be closed.
pause
