@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Serious Game Web Launcher

rem Resolve paths from this file so the cloned repository can be moved freely.
set "LAUNCHER_DIR=%~dp0"
set "BACKEND_DIR=%LAUNCHER_DIR%code\backend"
set "WEB_DIR=%LAUNCHER_DIR%code\frontend\web"
set "WEB_URL=http://127.0.0.1:3001"
set "GAME_BACKEND_URL=http://127.0.0.1:8100"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem Local launcher defaults. Real API keys remain in the user's environment.
set "GAME_REPOSITORY=sqlite"
set "GAME_DATABASE_PATH=data/serious_game.db"
set "ROLE_LLM_TIMEOUT_SECONDS=15"
set "ROLE_LLM_MAX_RETRIES=1"

if not exist "%BACKEND_DIR%\run_server.py" goto :missing_project
if not exist "%BACKEND_DIR%\requirements.txt" goto :missing_project
if not exist "%WEB_DIR%\package.json" goto :missing_project

set "PYTHON_EXE="
call :try_python "%BACKEND_DIR%\.venv\Scripts\python.exe"
call :try_python "%LAUNCHER_DIR%.venv\Scripts\python.exe"
call :try_python "D:\ProgramData\anaconda3\python.exe"
call :try_python "C:\ProgramData\anaconda3\python.exe"
call :try_python "C:\ProgramData\Anaconda3\python.exe"
for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do call :try_python "%%~fD\python.exe"
for /f "delims=" %%I in ('where python.exe 2^>nul') do call :try_python "%%I"
for /f "delims=" %%I in ('py.exe -3 -c "import sys; print(sys.executable)" 2^>nul') do call :try_python "%%I"
if not defined PYTHON_EXE goto :missing_python

set "NODE_EXE="
for /f "delims=" %%I in ('where node.exe 2^>nul') do if not defined NODE_EXE set "NODE_EXE=%%I"
if not defined NODE_EXE goto :missing_node
"%NODE_EXE%" -e "const [a,b]=process.versions.node.split('.').map(Number);process.exit(a>22||(a===22&&b>=13)?0:1)" >nul 2>&1
if errorlevel 1 goto :old_node

set "NPM_CMD="
for /f "delims=" %%I in ('where npm.cmd 2^>nul') do if not defined NPM_CMD set "NPM_CMD=%%I"
if not defined NPM_CMD goto :missing_node

echo [1/4] Checking backend dependencies...
"%PYTHON_EXE%" -c "import fastapi, pydantic, uvicorn, pymysql, cryptography" >nul 2>&1
if errorlevel 1 (
    echo Installing missing Python dependencies. Please wait...
    "%PYTHON_EXE%" -m pip install -r "%BACKEND_DIR%\requirements.txt"
    if errorlevel 1 goto :install_failed
)

echo [2/4] Checking web dependencies...
if not exist "%WEB_DIR%\node_modules\.bin\vinext.cmd" (
    pushd "%WEB_DIR%"
    call "%NPM_CMD%" install
    set "NPM_EXIT=%ERRORLEVEL%"
    popd
    if not "%NPM_EXIT%"=="0" goto :web_install_failed
)

if /i "%~1"=="--check" (
    echo Check passed: Python, Node.js, backend, and web dependencies are ready.
    echo Web address: %WEB_URL%
    exit /b 0
)

echo [3/4] Starting backend with hot reload...
powershell.exe -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8100/health/ready' -TimeoutSec 2; if ($r.repository -eq 'sqlite') { exit 0 } else { exit 2 } } catch { exit 1 }" >nul 2>&1
set "BACKEND_STATUS=%ERRORLEVEL%"
if "%BACKEND_STATUS%"=="2" goto :wrong_repository
if not "%BACKEND_STATUS%"=="0" (
    start "Serious Game Backend - Hot Reload" /D "%BACKEND_DIR%" "%ComSpec%" /k ""%PYTHON_EXE%" run_server.py --reload"
)

echo Waiting for the backend...
powershell.exe -NoProfile -Command "$limit=(Get-Date).AddSeconds(45); do { try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8100/health/ready' -TimeoutSec 2; if ($r.status -eq 'ready' -and $r.repository -eq 'sqlite') { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $limit); exit 1" >nul 2>&1
if errorlevel 1 goto :backend_failed

echo [4/4] Starting the web client with hot reload...
powershell.exe -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri '%WEB_URL%' -TimeoutSec 2; if ($r.StatusCode -eq 200 -and $r.Content -match '浊流之上') { exit 0 } else { exit 2 } } catch { exit 1 }" >nul 2>&1
set "WEB_STATUS=%ERRORLEVEL%"
if "%WEB_STATUS%"=="2" goto :wrong_web
if not "%WEB_STATUS%"=="0" (
    start "Serious Game Web - Hot Reload" /D "%WEB_DIR%" "%ComSpec%" /k ""%NPM_CMD%" run dev -- --port 3001"
)

echo Waiting for the web client...
powershell.exe -NoProfile -Command "$limit=(Get-Date).AddSeconds(60); do { try { $r=Invoke-WebRequest -UseBasicParsing -Uri '%WEB_URL%' -TimeoutSec 3; if ($r.StatusCode -eq 200 -and $r.Content -match '浊流之上') { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $limit); exit 1" >nul 2>&1
if errorlevel 1 goto :web_failed

echo.
echo Web game is ready: %WEB_URL%
echo Keep the backend and web windows open while playing.
start "" "%WEB_URL%"
exit /b 0

:missing_project
echo [ERROR] Project files were not found beside BEGIN.BAT.
pause
exit /b 1

:missing_python
echo [ERROR] Python 3.11 or newer was not found.
echo Install Python and enable Add Python to PATH.
pause
exit /b 1

:missing_node
echo [ERROR] Node.js and npm were not found.
echo Install Node.js 22.13 or newer, then reopen this launcher.
pause
exit /b 1

:old_node
echo [ERROR] Node.js 22.13 or newer is required.
echo Current version:
"%NODE_EXE%" --version
pause
exit /b 1

:install_failed
echo [ERROR] Python dependency installation failed.
pause
exit /b 1

:web_install_failed
echo [ERROR] Web dependency installation failed.
pause
exit /b 1

:backend_failed
echo [ERROR] The backend did not become ready within 45 seconds.
echo Check the backend window for the detailed error.
pause
exit /b 1

:web_failed
echo [ERROR] The web client did not become ready within 60 seconds.
echo Check the web window for the detailed error.
pause
exit /b 1

:wrong_repository
echo [ERROR] Port 8100 is occupied by a backend that is not using SQLite.
echo Close the old backend process, then run BEGIN.BAT again.
pause
exit /b 1

:wrong_web
echo [ERROR] Port 3001 is occupied by another website.
echo Close the process using port 3001, then run BEGIN.BAT again.
pause
exit /b 1

:try_python
if defined PYTHON_EXE exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_EXE=%~1"
exit /b 0
