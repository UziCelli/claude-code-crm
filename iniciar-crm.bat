@echo off
chcp 65001 >nul
title VFITCOACH CRM
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Primeira execucao: preparando o ambiente ^(1-2 minutos^)...
    python -m venv .venv || (echo ERRO: Python 3 nao encontrado. Instale em https://www.python.org/downloads/ e marque "Add to PATH". & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || (echo ERRO ao instalar dependencias. & pause & exit /b 1)
    echo Ambiente pronto.
)

powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop')+'\VFITCOACH CRM.lnk'; if (-not (Test-Path $d)) { $s=(New-Object -ComObject WScript.Shell).CreateShortcut($d); $s.TargetPath='%~f0'; $s.WorkingDirectory='%~dp0'; $s.Description='Abrir o CRM VFITCOACH'; $s.Save(); Write-Host 'Atalho criado na Area de Trabalho.' }"

echo Iniciando o CRM em http://localhost:8765 ...
start "" /min cmd /c "timeout /t 3 >nul & start "" http://localhost:8765"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8765
pause
