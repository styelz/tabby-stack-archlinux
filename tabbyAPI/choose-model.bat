@echo off
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" select_model.py --ask
if errorlevel 1 exit /b 1
echo.
echo Profile written. Start TabbyAPI with start.bat
pause
