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
if not exist "data" mkdir "data"

rem Cria o atalho so se nenhum atalho da Area de Trabalho (com qualquer nome) ja abrir este arquivo.
powershell -NoProfile -Command "$sh=New-Object -ComObject WScript.Shell; $d=[Environment]::GetFolderPath('Desktop'); $tem=Get-ChildItem $d -Filter *.lnk | Where-Object { $sh.CreateShortcut($_.FullName).TargetPath -eq '%~f0' }; if (-not $tem) { $s=$sh.CreateShortcut($d+'\VFITCOACH CRM.lnk'); $s.TargetPath='%~f0'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0vfitcoach_crm.ico'; $s.Description='Abrir o CRM VFITCOACH'; $s.Save(); Write-Host 'Atalho criado na Area de Trabalho.' }"

rem Sobe o servidor sem janela (se ainda nao estiver rodando), espera ele responder e abre o navegador.
rem Para desligar: botao "Encerrar" no menu do CRM. Mensagens do servidor ficam em data\crm.log e data\crm-erro.log.
powershell -NoProfile -Command "function ok { try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8765); $c.Close(); $true } catch { $false } }; if (-not (ok)) { Write-Host 'Iniciando o CRM...'; Start-Process -WindowStyle Hidden -FilePath '%~dp0.venv\Scripts\python.exe' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8765' -WorkingDirectory '%~dp0' -RedirectStandardOutput '%~dp0data\crm.log' -RedirectStandardError '%~dp0data\crm-erro.log'; for ($i=0; $i -lt 60 -and -not (ok); $i++) { Start-Sleep -Milliseconds 500 } }; if (ok) { Start-Process 'http://localhost:8765' } else { exit 1 }"
if errorlevel 1 (
    echo.
    echo ERRO: o CRM nao iniciou. Mensagens do servidor:
    type "data\crm-erro.log"
    pause
)
