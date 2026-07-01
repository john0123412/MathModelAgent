@echo off
chcp 65001 >nul 2>&1
echo =============================================
echo  Environment Check
echo =============================================
echo.

echo [1] Docker:
docker --version 2>nul
if %errorlevel% neq 0 (
    echo   NOT FOUND
) else (
    echo   OK
)
echo.

echo [2] Docker Desktop running:
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo   NOT RUNNING
) else (
    echo   RUNNING
)
echo.

echo [3] Redis container:
docker ps -a --format "{{.Names}} {{.Status}}" 2>nul | findstr "redis-mma"
if %errorlevel% neq 0 (
    echo   NOT FOUND
)
echo.

echo [4] Python:
D:\workspace\MathModelAgent\backend\.venv\Scripts\python.exe --version 2>nul
if %errorlevel% neq 0 (
    echo   NOT FOUND
)
echo.

echo [5] Node.js:
node --version 2>nul
if %errorlevel% neq 0 (
    echo   NOT FOUND
)
echo.

echo [6] Port 8003:
netstat -ano | findstr ":8003" | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo   IN USE
) else (
    echo   FREE
)
echo.

echo [7] Port 5173:
netstat -ano | findstr ":5173" | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo   IN USE
) else (
    echo   FREE
)
echo.

echo =============================================
echo Check complete.
pause
