@echo off
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" switch_model.py %*
if errorlevel 1 exit /b 1
