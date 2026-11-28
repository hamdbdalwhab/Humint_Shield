@echo off
chcp 65001 >nul
title HUMINT Shield - USB Local Companion Agent
setlocal

cd /d "%~dp0"

echo =======================================================================
echo          HUMINT SHIELD - USB LOCAL COMPANION AGENT LAUNCHER
echo =======================================================================
echo.

set "PYTHON_EXE="
set "AGENT_SCRIPT="

:: Check if virtualenv exists in current folder or hument_project subfolder
if exist "backend\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=backend\.venv\Scripts\python.exe"
    set "AGENT_SCRIPT=deployment_agent.py"
    echo [*] Detected virtual environment: backend\.venv
) else if exist "hument_project\backend\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=hument_project\backend\.venv\Scripts\python.exe"
    set "AGENT_SCRIPT=hument_project\deployment_agent.py"
    echo [*] Detected virtual environment: hument_project\backend\.venv
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=python"
        echo [*] Using system Python from PATH.
    )
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python is not installed or could not be found!
    echo Please install Python 3.10+ and add it to your PATH.
    echo.
    pause
    exit /b 1
)

:: Locate deployment_agent.py if not already set
if "%AGENT_SCRIPT%"=="" (
    if exist "deployment_agent.py" (
        set "AGENT_SCRIPT=deployment_agent.py"
    ) else if exist "hument_project\deployment_agent.py" (
        set "AGENT_SCRIPT=hument_project\deployment_agent.py"
    ) else (
        echo [ERROR] Could not find deployment_agent.py in current directory!
        echo.
        pause
        exit /b 1
    )
)

:: Check and auto-install required packages
echo [*] Checking required dependencies...
"%PYTHON_EXE%" -c "import websockets, psutil" >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] Installing required dependencies: websockets psutil...
    "%PYTHON_EXE%" -m pip install websockets psutil
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies via pip.
        pause
        exit /b 1
    )
)
echo [OK] All dependencies verified.
echo.
echo [*] Starting USB Companion Agent on ws://127.0.0.1:8089...
echo [*] Keep this window OPEN while running USB awareness campaigns.
echo.

"%PYTHON_EXE%" "%AGENT_SCRIPT%"

if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Agent process exited with code %errorlevel%.
)

echo.
echo Press any key to exit...
pause >nul
