@echo off
echo Setting up Correct Conda environment for Alas...

set "CONDA_ROOT=D:\Environments\Anaconda"
set "ENV_ROOT=C:\Users\CD\.conda\envs\alas"

REM Manually add all necessary Conda paths
set "PATH=%CONDA_ROOT%;%CONDA_ROOT%\Scripts;%CONDA_ROOT%\Library\bin;%ENV_ROOT%;%ENV_ROOT%\Scripts;%ENV_ROOT%\Library\bin;%PATH%"

REM Change directory to the script's location
cd /d "%~dp0"
echo Changed current directory to %cd%
echo.

echo Attempting to start Alas...
.\webapp\dist\win-unpacked\alas.exe

echo.
echo Script finished.
pause