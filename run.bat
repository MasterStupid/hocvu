@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto start

set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE goto no_python

:start
echo Starting HocVu AI (React Voice Assistant + FastAPI)...
echo Keep this window open while using the project. Press Ctrl+C to stop.
"%PYTHON_EXE%" artifacts\hocvu\local_run.py --open %*
if not errorlevel 1 goto end
echo.
echo Neu ban moi tai repo lan dau, hay cai dat moi truong:
echo   uv sync --python 3.13  ^(hoac: python -m pip install -r requirements.txt^)
echo   pnpm install ^&^& pnpm --filter @workspace/hocvu run build
pause
goto end

:no_python
echo Python was not found. Install Python 3.12 or 3.13.
pause

:end
endlocal
