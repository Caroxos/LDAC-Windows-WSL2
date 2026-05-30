@echo off
:: ================================================================
:: LDAC Audio - PRODUCTION ENVIRONMENT (Main Alpine)
:: ================================================================
:: Non-elevated launcher for the LDAC system tray application.
:: Targets Alpine with a 320 MB RAM limit.

:: pythonw executes the script without opening any console window
start "" pythonw "C:\LDAC_Audio\ldac_tray.py"
