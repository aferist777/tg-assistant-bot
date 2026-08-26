@echo off
REM Launch the personal Telegram assistant bot.
REM The OpenClaw gateway (the AI "brain") autostarts at Windows login.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" bot.py
pause
