@echo off
setlocal
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" goto dependencies
py -3 -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
    goto created
)
python -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if errorlevel 1 (
    echo Install Python 3.10 or newer from python.org, then run this file again.
    goto failed
)
python -m venv .venv
:created
if not exist ".venv\Scripts\python.exe" goto failed
:dependencies
".venv\Scripts\python.exe" -c "import PyQt6.QtWidgets, icmplib, psutil" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies. Internet access is required for the first run.
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" jitterscope.py
if errorlevel 1 goto failed
popd
exit /b 0
:failed
echo Startup failed. See the message above.
pause
popd
exit /b 1
