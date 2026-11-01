@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3.12 -m unittest discover -s tests -v
pause
