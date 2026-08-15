@echo off
echo ==================================================================
echo         Alas Final Launcher
echo ==================================================================
echo.
echo This script will set up the correct Conda environment and then
echo launch the Alas application.
echo.

REM --- Configuration ---
REM Path to your main Anaconda/Miniconda installation
set "CONDA_ROOT=D:\Environments\Anaconda"
REM Path to the 'alas' environment we created
set "ENV_ROOT=D:\Environments\Anaconda\envs\alas"

echo Setting up environment paths...
REM Manually add all necessary Conda and environment paths to the front of the PATH variable
set "PATH=%CONDA_ROOT%;%CONDA_ROOT%\Scripts;%CONDA_ROOT%\Library\bin;%ENV_ROOT%;%ENV_ROOT%\Scripts;%ENV_ROOT%\Library\bin;%PATH%"

REM Change directory to the script's location to ensure the app starts in the project root
cd /d "%~dp0"
echo Running in directory: %cd%
echo.

echo Starting Alas...
.\webapp\dist\win-unpacked\alas.exe

REM Check the exit code of the application
if %errorlevel% neq 0 (
    echo.
    echo -----------------------------------------------------------
    echo ERROR: Alas.exe exited with an error code.
    echo If you saw a "spawn ENOENT" error, it means the application
    echo could not correctly start the Python backend.
    echo -----------------------------------------------------------
) else (
    echo Alas.exe exited normally.
)

echo.
echo Script finished.
pause
