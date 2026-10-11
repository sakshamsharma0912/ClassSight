@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
    set "SPA_PYTHON=py -3"
) else (
    set "SPA_PYTHON=python"
)
if not exist ".venv\Scripts\python.exe" (
    %SPA_PYTHON% -m venv .venv
    if errorlevel 1 goto setup_error
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto setup_error
echo.
echo ClassSight
echo Open http://127.0.0.1:5000 in your browser.
echo Register a teacher account; invite students from their profiles.
echo Press Ctrl+C to stop the application.
echo.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto setup_error
exit /b 0
:setup_error
echo.
echo Setup failed. Install Python 3.10 or later and check your internet connection.
echo Review the error above and the README troubleshooting instructions.
pause
exit /b 1
