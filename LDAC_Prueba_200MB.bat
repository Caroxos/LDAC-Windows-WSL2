@echo off
:: ================================================================
:: LDAC Audio - TEST ENVIRONMENT (Alpine-Test, 320 MB RAM)
:: ================================================================
:: Non-elevated launcher for the LDAC system tray application.
:: Targets Alpine-Test with a 320 MB RAM limit.

:: pythonw ejecuta el script sin abrir ninguna ventana de consola
start "" pythonw "C:\LDAC_Audio\ldac_tray_test.py"

