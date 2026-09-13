@echo off
cd /d "%~dp0"
py -3 tools\ib.py start
if errorlevel 1 pause
