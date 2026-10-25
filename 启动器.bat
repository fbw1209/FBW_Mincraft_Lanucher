@echo off
cd /d "%~dp0"
if exist "dist\FML.exe" (
    start "" "dist\FML.exe"
    exit /b
)
where pythonw >nul 2>nul
if errorlevel 1 (
    python main.pyw
) else (
    start "" pythonw "%~dp0main.pyw"
)
