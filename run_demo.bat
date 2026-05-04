@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=D:\Anaconda\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo Demo: asking Repo Agent where the streaming chat handler is.
echo.
"%PYTHON_EXE%" -m repo_agent ask --repo ".\examples\simple_agent_app" --question "聊天流式接口最终调用哪个处理函数？" --force-rebuild

echo.
echo Press any key to close.
pause >nul
