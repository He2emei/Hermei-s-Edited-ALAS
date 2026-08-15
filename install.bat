@echo off
setlocal

echo ==================================================================
echo AzurLaneAutoScript One-Click Installer
echo ==================================================================
echo.
echo This script will automate the installation of all Python and
echo JavaScript dependencies.
echo.
echo IMPORTANT: Please ensure you have already installed:
echo   1. Anaconda/Miniconda (and the 'conda' command works)
echo   2. Node.js (LTS version, so the 'npm' command works)
echo.
pause
echo.

echo [1/5] Creating Conda environment 'alas' with Python 3.7.6...
conda create -n alas python==3.7.6 -y
if %errorlevel% neq 0 (
    echo ERROR: Failed to create Conda environment.
    goto :error
)
echo Environment 'alas' created successfully.
echo.

echo [2/5] Installing the complex 'PyAV' package from Conda-Forge...
call conda run -n alas conda install -c conda-forge av -y
if %errorlevel% neq 0 (
    echo ERROR: Failed to install PyAV.
    goto :error
)
echo PyAV installed successfully.
echo.

echo [3/5] Installing all other Python dependencies via pip...
call conda run -n alas pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install Python dependencies from requirements.txt.
    goto :error
)
echo Python dependencies installed successfully.
echo.

echo [4/5] Installing JavaScript package manager 'Yarn'...
npm install --global yarn
if %errorlevel% neq 0 (
    echo ERROR: Failed to install Yarn.
    goto :error
)
echo Yarn installed successfully.
echo.

echo [5/5] Installing WebApp dependencies...
cd webapp
call yarn install
if %errorlevel% neq 0 (
    echo ERROR: Failed to install WebApp dependencies.
    cd ..
    goto :error
)
cd ..
echo WebApp dependencies installed successfully.
echo.

echo ==================================================================
echo                           SUCCESS!
echo ==================================================================
echo All dependencies have been installed.
echo.
echo -------------------- CRITICAL FINAL STEP -------------------------
echo You must now manually update the configuration file.
echo.
echo Please find the exact path to your 'alas' python.exe below:
echo.
call conda env list
echo.
echo Copy the path for the 'alas' environment and add '\python.exe'
echo to the end of it.
echo.
echo Then, open the file 'config\deploy.yaml' and paste the full
echo path into the 'PythonExecutable' field.
echo.
echo Example: C:\Users\YourName\.conda\envs\alas\python.exe
echo ------------------------------------------------------------------
echo.
goto :end

:error
echo.
echo ==================================================================
echo                       INSTALLATION FAILED
echo ==================================================================
echo An error occurred. Please check the messages above.

:end
echo.
pause
