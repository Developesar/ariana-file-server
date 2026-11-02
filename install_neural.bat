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
".venv\Scripts\python.exe" -m pip install --progress-bar off -r requirements-neural.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" model_setup.py
if errorlevel 1 goto failed
echo Ready. Restart launch.bat and choose QuickMT.
pause
popd
exit /b 0
:failed
echo Setup failed. Check the error above and run this installer again to resume.
pause
popd
exit /b 1
