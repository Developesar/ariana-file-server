@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
chcp 65001 >nul
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 py -3 -m venv .venv
  if errorlevel 1 python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-dorna.txt
if errorlevel 1 goto failed
where nvidia-smi >nul 2>&1
if errorlevel 1 goto cpu
echo Installing CUDA 12.4 llama.cpp wheel for NVIDIA GPU...
".venv\Scripts\python.exe" -m pip install llama-cpp-python==0.3.35 --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
if errorlevel 1 goto cpu
".venv\Scripts\python.exe" -m pip install -r requirements-cuda.txt
if errorlevel 1 goto cpu
if not exist ".runtime-download" mkdir ".runtime-download"
".venv\Scripts\python.exe" -m pip download llama-cpp-python==0.3.35 --only-binary=:all: --no-deps --index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --dest .runtime-download
if errorlevel 1 goto cpu
".venv\Scripts\python.exe" prepare_llama_runtime.py
if not errorlevel 1 goto model
echo CUDA installation failed. Falling back to the CPU wheel.
:cpu
".venv\Scripts\python.exe" -m pip install --force-reinstall llama-cpp-python==0.3.35 --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if errorlevel 1 goto failed
:model
".venv\Scripts\python.exe" direct_model_setup.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "from direct_dorna_backend import runtime_status; print(runtime_status())"
if errorlevel 1 goto failed
echo.
echo Dorna 2 direct runtime is ready. GPU is preferred; CPU/RAM handles remaining layers.
pause
popd
exit /b 0
:failed
echo.
echo Setup failed. Review the error above.
pause
popd
exit /b 1
