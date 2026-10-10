@echo off
chcp 65001 >nul
title VFITCOACH CRM
cd /d "%~dp0"

rem Modo servidor: "iniciar-crm.bat /servidor" (inicio automatico do Windows, criado por configurar-pc-servidor.ps1).
rem So liga o CRM em segundo plano: nao cria atalho, nao abre o navegador e nunca espera tecla.
set "CRM_SERVIDOR="
if /i "%~1"=="/servidor" set "CRM_SERVIDOR=1"

if not exist ".venv\Scripts\python.exe" (
    echo Primeira execucao: preparando o ambiente ^(1-2 minutos^)...
    py -3.13 -m venv .venv 2>nul || python -m venv .venv || (echo ERRO: Python 3 nao encontrado. Instale em https://www.python.org/downloads/ e marque "Add to PATH". & call :pausa & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || (echo ERRO ao instalar dependencias. & call :pausa & exit /b 1)
    echo Ambiente pronto.
)
rem Turso ligado (.env) e biblioteca faltando (ex.: depois de um git pull): instala o que faltar.
if exist ".env" (
    ".venv\Scripts\python.exe" -c "import libsql" 2>nul || ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)
if not exist "data" mkdir "data"

rem Cria o atalho so se nenhum atalho da Area de Trabalho (com qualquer nome) ja abrir este arquivo. No modo servidor, pula.
if not defined CRM_SERVIDOR powershell -NoProfile -Command "$sh=New-Object -ComObject WScript.Shell; $d=[Environment]::GetFolderPath('Desktop'); $tem=Get-ChildItem $d -Filter *.lnk | Where-Object { $sh.CreateShortcut($_.FullName).TargetPath -eq '%~f0' }; if (-not $tem) { $s=$sh.CreateShortcut($d+'\VFITCOACH CRM.lnk'); $s.TargetPath='%~f0'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0vfitcoach_crm.ico'; $s.Description='Abrir o CRM VFITCOACH'; $s.Save(); Write-Host 'Atalho criado na Area de Trabalho.' }"

rem Sobe o servidor sem janela (se ainda nao estiver rodando), espera ele responder e abre o navegador (no modo servidor, nao abre).
rem Para desligar: botao "Encerrar" no menu do CRM. Mensagens do servidor ficam em data\crm.log e data\crm-erro.log.
powershell -NoProfile -Command "function ok { try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8765); $c.Close(); $true } catch { $false } }; if (-not (ok)) { Write-Host 'Iniciando o CRM...'; Start-Process -WindowStyle Hidden -FilePath '%~dp0.venv\Scripts\python.exe' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8765' -WorkingDirectory '%~dp0' -RedirectStandardOutput '%~dp0data\crm.log' -RedirectStandardError '%~dp0data\crm-erro.log'; for ($i=0; $i -lt 60 -and -not (ok); $i++) { Start-Sleep -Milliseconds 500 } }; if (ok) { if (-not $env:CRM_SERVIDOR) { Start-Process 'http://localhost:8765' } } else { exit 1 }"
if errorlevel 1 (
    echo.
    echo ERRO: o CRM nao iniciou. Mensagens do servidor:
    type "data\crm-erro.log"
    call :pausa
    exit /b 1
)
if defined CRM_SERVIDOR echo CRM ligado em segundo plano: http://localhost:8765
exit /b 0

:pausa
rem Espera uma tecla so na abertura normal: no modo servidor ninguem esta olhando a janela.
if not defined CRM_SERVIDOR pause
exit /b
