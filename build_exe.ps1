# 盲水印 GUI 打包脚本
# 用法：在本目录下执行：  powershell -ExecutionPolicy Bypass -File build_exe.ps1
$ErrorActionPreference = 'Stop'
$ws = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ws

# 1) 使用支持 Python 3.14 的最新 PyInstaller（老版本 6.10 打出的 exe 会闪退）
py -3 -m pip install -U pyinstaller
py -3 -m PyInstaller --version

# 2) 打包：使用 ui_watermark.spec（内含体积优化，过滤无用 DLL 与 Qt/科学计算模块）
py -3 -m PyInstaller --noconfirm --clean ui_watermark.spec

Write-Host "== 打包完成 =="
Get-Item ".\dist\ui_watermark.exe" | Select-Object Name, Length, LastWriteTime