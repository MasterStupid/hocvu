@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_EXE=%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
if exist "%PYTHON_EXE%" goto start

set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE goto no_python

:start
set "HV_SEMANTIC=0"
echo Starting HocVu AI at http://127.0.0.1:8000 ...
echo Keep this window open while using the project. Press Ctrl+C to stop.
"%PYTHON_EXE%" manage.py serve --open %*
if not errorlevel 1 goto end
echo.
echo Server could not start. For first-time setup run:
echo python -m pip install -r requirements.txt
pause
goto end

:no_python
echo Python was not found. Install Python 3.10 or newer.
pause

:end
endlocal
