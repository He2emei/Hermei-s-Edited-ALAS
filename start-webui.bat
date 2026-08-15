@echo off
echo ==================================================================
echo         Alas Web UI Launcher
echo ==================================================================
echo.
echo This script will set up the correct Conda environment and start
echo the Alas Web UI backend.
echo.

REM --- Configuration ---
set "CONDA_ROOT=D:\Environments\Anaconda"
set "ENV_ROOT=D:\Environments\Anaconda\envs\alas"

echo Setting up environment paths...
REM Manually add all necessary Conda and environment paths
set "PATH=%CONDA_ROOT%;%CONDA_ROOT%\Scripts;%CONDA_ROOT%\Library\bin;%ENV_ROOT%;%ENV_ROOT%\Scripts;%ENV_ROOT%\Library\bin;%PATH%"

REM Change directory to the script's location
cd /d "%~dp0"
echo Running in directory: %cd%
echo.

echo ==================================================================
echo Starting Alas Web UI...
echo.
echo You can now access Alas by opening your web browser to:
echo   http://127.0.0.1:22267
echo ==================================================================
echo.

REM Start the python gui script
python gui.py

echo.
echo Script finished.
pause
