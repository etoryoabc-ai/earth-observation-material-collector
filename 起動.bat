@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 をインストールしてください。https://www.python.org/downloads/
  pause
  exit /b 1
)
py -3.12 app.py
if errorlevel 1 (
  echo 起動できませんでした。Pythonの設定またはポート8765を確認してください。
  pause
)
