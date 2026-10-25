param(
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not $NoInstall) {
    python -m pip install -r requirements.txt
    python -m pip install pyinstaller
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "FML" `
    --icon "assets\icon.ico" `
    --add-data "assets;assets" `
    --collect-all customtkinter `
    "main.pyw"

Write-Host ""
Write-Host "构建完成：dist\FML.exe"
Write-Host "dist\FML.exe 是单文件便携版，可以复制到任意可写目录运行。"
