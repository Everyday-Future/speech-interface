@echo off
title Speech Interface Launcher
echo Starting Speech-to-Text Interface...
echo.

:: Check if Python is installed
python --version > nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Python is not installed or not in PATH.
    echo Please install Python from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: Set paths
set SCRIPT_DIR=%~dp0
set SCRIPT_PATH=%SCRIPT_DIR%main.pyw
set VENV_DIR=%SCRIPT_DIR%venv

:: Check if the Python script exists
if not exist "%SCRIPT_PATH%" (
    echo Error: Could not find main.py in the same directory.
    echo Please ensure the Python script is in the same folder as this batch file.
    echo.
    pause
    exit /b 1
)

:: Create and activate virtual environment if it does not exist
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if %ERRORLEVEL% neq 0 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Activate the virtual environment
call "%VENV_DIR%\Scripts\activate.bat"
if %ERRORLEVEL% neq 0 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

:: Check for required packages in the virtual environment
echo Checking required packages...
python -c "import tkinter, pyaudio, speech_recognition, pyperclip" > nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installing required packages in virtual environment...
    pip install -r requirements.txt
)

:: Run the Python script in the virtual environment
echo All requirements met! Starting application...
pythonw "%SCRIPT_PATH%"

:: Deactivate the virtual environment
call "%VENV_DIR%\Scripts\deactivate.bat"

exit /b 0