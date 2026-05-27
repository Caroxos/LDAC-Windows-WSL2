@echo off
:: ================================================================
:: LDAC Audio - Portable Launcher
:: ================================================================
:: Runs the LDAC system tray application from the current directory.

:: pythonw executes the script without opening any console window
start "" pythonw "%~dp0ldac_tray.py"
