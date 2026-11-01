@echo off
title Market Brief
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting things up. This takes a minute or two...
  echo.
  %PY% -m venv .venv
  if errorlevel 1 goto nopython
  ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto pipfail
  echo.
  echo Setup done.
  echo.
)

".venv\Scripts\python.exe" main.py %*
pause
exit /b

:nopython
echo.
echo Python isn't installed yet.
echo Install it from https://www.python.org/downloads/
echo On the first install screen, tick "Add python.exe to PATH", then run this file again.
echo.
pause
exit /b

:pipfail
echo.
echo Setup couldn't download what it needs. Check your internet and run this file again.
rmdir /s /q .venv
pause
exit /b
