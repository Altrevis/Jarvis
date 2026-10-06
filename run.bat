@echo off
rem Launches MARK LV using the virtual environment setup.py created.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No .venv found -- run "python setup.py" first. 1>&2
    exit /b 1
)

".venv\Scripts\python.exe" main.py %*
