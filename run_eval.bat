@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=D:\Anaconda\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo Running Repo Agent evaluation...
echo.
"%PYTHON_EXE%" -m repo_agent eval

echo.
echo Press any key to close.
pause >nul
