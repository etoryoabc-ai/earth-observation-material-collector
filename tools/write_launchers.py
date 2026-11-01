"""Generate byte-stable Windows launchers: ASCII, no BOM, CRLF only."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
TEMPLATE='''@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Earth Observation Material Collector
pushd "%~dp0"
if errorlevel 1 goto folder_error
set "APP_EXIT=1"
set "PYTHON_CMD="
where.exe py.exe >nul 2>&1
if errorlevel 1 goto try_python
py.exe -3.12 -I -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto try_python
set "PYTHON_CMD=py.exe -3.12"
goto run_app
:try_python
where.exe python.exe >nul 2>&1
if errorlevel 1 goto python_missing
python.exe -I -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto python_missing
set "PYTHON_CMD=python.exe"
:run_app
if not exist "%~dp0launcher.py" goto files_missing
if not exist "%~dp0app.py" goto files_missing
%PYTHON_CMD% -X utf8 -u "%~dp0launcher.py" __MODE__
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" goto app_error
echo.
echo Application stopped.
goto finish
:python_missing
echo.
echo ERROR: Python 3.12 was not found.
echo Install Python 3.12 and enable the Python Launcher or PATH option.
echo https://www.python.org/downloads/
goto finish
:files_missing
echo.
echo ERROR: Application files are missing. Extract ALL files from the ZIP first.
goto finish
:app_error
echo.
echo ERROR: Application exited with code %APP_EXIT%.
echo See the message above and the logs folder for details.
goto finish
:finish
echo.
echo Press any key to close this window.
pause >nul
popd
endlocal & exit /b %APP_EXIT%
:folder_error
echo ERROR: Cannot open the application folder. Extract the ZIP to a writable folder.
pause
endlocal & exit /b 1
'''

def expected(mode):
    return TEMPLATE.replace('__MODE__',mode).replace('\n','\r\n').encode('ascii')

if __name__=='__main__':
    for name,mode in [('起動.bat',''),('テスト.bat','--test')]:
        (ROOT/name).write_bytes(expected(mode))
