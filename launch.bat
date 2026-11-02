@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 py -3 -m venv .venv
  if errorlevel 1 python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import customtkinter, openpyxl; import direct_dorna_backend as d; d._register_cuda_runtime(); import llama_cpp" >nul 2>&1
if errorlevel 1 (
  echo Direct Dorna runtime is not installed. Run install_dorna_gpu.bat once.
  pause
  goto failed
)
".venv\Scripts\python.exe" -c "import llama_cpp" >nul 2>&1
if errorlevel 1 (
  echo Direct Dorna runtime is not installed. Run install_dorna_gpu.bat first.
  pause
  goto failed
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto failed
popd
exit /b 0
:failed
echo Setup or application failed. Python 3.11 or 3.12 is recommended.
pause
popd
exit /b 1
