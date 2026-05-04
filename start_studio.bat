@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=D:\Anaconda\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo Starting Repo Agent Studio...
echo.
echo If the browser does not open automatically, visit:
echo http://127.0.0.1:8787
echo.

start "" http://127.0.0.1:8787
"%PYTHON_EXE%" -m repo_agent serve --host 127.0.0.1 --port 8787

echo.
echo Studio stopped. Press any key to close.
pause >nul
