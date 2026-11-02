@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements-offline.txt
if errorlevel 1 goto failed
echo Installed. Import a compatible local Persian-English .argosmodel in the GUI.
pause
popd
exit /b 0
:failed
echo Installation failed. Check Python version and network access.
pause
popd
exit /b 1
