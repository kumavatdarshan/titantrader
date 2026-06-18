@echo off
REM TitanTrader - One-Click Startup
REM This script installs dependencies and starts the bot

cd /d C:\Users\lenovo\Downloads\titantrader

REM Install/update dependencies silently
echo Installing dependencies...
pip install -q -r requirements.txt

REM Clear old logs
if exist logs\ del /Q logs\*.log 2>nul

REM Start the bot
echo.
echo ================================================
echo TITANTRADER STARTING...
echo Dashboard will open at http://localhost:8000
echo Press Ctrl+C to stop the bot
echo ================================================
echo.
python main.py

pause
