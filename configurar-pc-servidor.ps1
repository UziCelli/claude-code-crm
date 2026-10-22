# Prepara este PC para ser o servidor do CRM no celular (Cloudflare Tunnel -> http://localhost:8765).
# Rode uma vez, na pasta do CRM, num PowerShell normal (nao precisa ser Administrador):
#   powershell -ExecutionPolicy Bypass -File .\configurar-pc-servidor.ps1
# Para tirar o inicio automatico:
#   powershell -ExecutionPolicy Bypass -File .\configurar-pc-servidor.ps1 -Desfazer
# Arquivo so com caracteres ASCII (sem acentos): o Windows PowerShell 5.1 le acentos errado em arquivo sem BOM.
param(
    [switch]$Desfazer
)

$pasta = $PSScriptRoot
if (-not $pasta) { $pasta = (Get-Location).Path }
$bat = Join-Path $pasta 'iniciar-crm.bat'
$atalho = Join-Path ([Environment]::GetFolderPath('Startup')) 'VFITCOACH CRM servidor.lnk'
$comando = 'powershell -ExecutionPolicy Bypass -File .\configurar-pc-servidor.ps1'

function Titulo([string]$texto) { Write-Host ''; Write-Host $texto -ForegroundColor Cyan }
function Ok([string]$texto) { Write-Host "  OK: $texto" -ForegroundColor Green }
function Aviso([string]$texto) { Write-Host "  ATENCAO: $texto" -ForegroundColor Yellow }
function Linha([string]$texto) { Write-Host "  $texto" }

function Fim([int]$codigo) {
    Write-Host ''
    Read-Host 'Aperte Enter para terminar' | Out-Null
    exit $codigo
}

function CrmRodando {
    try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', 8765); $c.Close(); return $true } catch { return $false }
}

function Energia([string]$opcao, [string]$texto) {
    try {
        $saida = & powercfg.exe /change $opcao 0 2>&1
        if ($LASTEXITCODE -ne 0) { throw "$saida" }
        Ok $texto
    } catch {
        Aviso "Nao consegui ajustar: $texto."
        Linha 'Faca na mao: Configuracoes > Sistema > Energia > Tela e suspensao > "Quando conectado": Nunca.'
    }
}

# ---------- Desfazer ----------
if ($Desfazer) {
    Titulo 'Desfazer o inicio automatico do CRM'
    if (Test-Path -LiteralPath $atalho) {
        try {
            Remove-Item -LiteralPath $atalho -Force -ErrorAction Stop
            Ok 'Atalho removido. O CRM nao liga mais sozinho ao entrar no Windows.'
        } catch {
            Aviso "Nao consegui apagar o atalho: $atalho"
            Linha 'Apague na mao: Windows+R, digite shell:startup, Enter, e apague "VFITCOACH CRM servidor".'
        }
    } else {
        Ok 'Nao havia inicio automatico. Nada para remover.'
    }
    Linha 'O CRM continua no PC: abra pelo atalho da Area de Trabalho, como antes.'
    Titulo 'Energia: nada foi mudado agora'
    Linha 'Para o PC voltar a dormir sozinho na tomada (exemplo: 30 minutos), rode:'
    Linha '  powercfg /change standby-timeout-ac 30'
    Linha 'Ou: Configuracoes > Sistema > Energia > Tela e suspensao.'
    Fim 0
}

# ---------- Configurar ----------
Write-Host 'VFITCOACH CRM: preparar este PC como servidor do celular' -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $bat)) {
    Aviso "Nao achei o iniciar-crm.bat em $pasta."
    Linha 'Deixe este arquivo na pasta do CRM e rode de novo.'
    Fim 1
}

Titulo '1. Ligar o CRM sozinho ao entrar no Windows'
try {
    if (Test-Path -LiteralPath $atalho) { Remove-Item -LiteralPath $atalho -Force -ErrorAction Stop }
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($atalho)
    $s.TargetPath = $bat
    $s.Arguments = '/servidor'
    $s.WorkingDirectory = $pasta
    $s.WindowStyle = 7   # minimizado
    $s.IconLocation = Join-Path $pasta 'vfitcoach_crm.ico'
    $s.Description = 'Liga o CRM VFITCOACH em segundo plano (acesso pelo celular)'
    $s.Save()
    Ok 'Atalho "VFITCOACH CRM servidor" criado na pasta Inicializar.'
    Linha 'Ao entrar no Windows, o CRM liga sem abrir o navegador.'
} catch {
    Aviso "Nao consegui criar o inicio automatico: $($_.Exception.Message)"
}

Titulo '2. Nao dormir na tomada'
Energia 'standby-timeout-ac' 'suspensao na tomada = nunca'
Energia 'hibernate-timeout-ac' 'hibernacao na tomada = nunca'
Linha 'Na bateria nada mudou.'

Titulo 'Se este PC for notebook: cuidado com a tampa'
Linha 'Fechar a tampa pode fazer o notebook dormir mesmo assim. Para evitar:'
Linha '  1. Aperte Windows+R, digite powercfg.cpl e aperte Enter.'
Linha '  2. Clique em "Escolher a funcao do fechamento da tampa".'
Linha '  3. Em "Ao fechar a tampa", na coluna "Conectado", escolha "Nao fazer nada".'
Linha '  4. Clique em "Salvar alteracoes".'
Linha 'Computador de mesa: pode pular esta parte.'

Titulo '3. Conferir o .env (chaves do acesso pelo celular)'
$arquivoEnv = Join-Path $pasta '.env'
$valores = @{}
if (Test-Path -LiteralPath $arquivoEnv) {
    foreach ($l in (Get-Content -LiteralPath $arquivoEnv -Encoding UTF8)) {
        $l = $l.Trim()
        $i = $l.IndexOf('=')
        if ($l -and -not $l.StartsWith('#') -and $i -gt 0) {
            $valores[$l.Substring(0, $i).Trim()] = $l.Substring($i + 1).Trim().Trim('"').Trim("'")
        }
    }
} else {
    Aviso 'Nao achei o arquivo .env nesta pasta.'
}
$faltam = @('CF_ACCESS_TEAM_DOMAIN', 'CF_ACCESS_AUD') | Where-Object { -not $valores[$_] }
if ($faltam) {
    Aviso ('Falta preencher no .env: ' + ($faltam -join ' e '))
    Linha 'Sem isso o CRM funciona no PC, mas o celular fica bloqueado (por seguranca). Para resolver:'
    Linha '  1. Abra o arquivo .env da pasta do CRM no Bloco de Notas.'
    Linha '     (Se nao existir: copie o .env.example e renomeie a copia para .env.)'
    Linha '  2. Deixe estas duas linhas assim:'
    Linha '       CF_ACCESS_TEAM_DOMAIN=SEU-TIME.cloudflareaccess.com'
    Linha '       CF_ACCESS_AUD=(o codigo "Application Audience (AUD) Tag")'
    Linha '  3. O AUD esta no Render: servico claude-code-crm > Environment > CF_ACCESS_AUD.'
    Linha '     Ou no Cloudflare Zero Trust: Access > Applications > CRM (procure "AUD").'
    Linha "  4. Salve o .env e rode de novo: $comando"
} else {
    Ok 'CF_ACCESS_TEAM_DOMAIN e CF_ACCESS_AUD preenchidos.'
    if ($valores['CF_ACCESS_TEAM_DOMAIN'] -notlike '*cloudflareaccess.com*') {
        Aviso 'CF_ACCESS_TEAM_DOMAIN parece errado. O certo termina em .cloudflareaccess.com (o nome do seu time, igual ao do Render)'
    }
}
$turso = @('TURSO_DATABASE_URL', 'TURSO_AUTH_TOKEN') | Where-Object {
    -not $valores[$_] -or $valores[$_] -like '*NOME-DO-BANCO*' -or $valores[$_] -like '*cole-o-token-aqui*'
}
if ($turso) {
    Aviso 'Turso nao configurado no .env: a reserva (Render) nao vai ver os mesmos dados do PC.'
} else {
    Ok 'Turso configurado (PC, celular e reserva usam o mesmo banco).'
}

Titulo '4. Tunel do Cloudflare (cloudflared)'
$servico = Get-Service -Name cloudflared -ErrorAction SilentlyContinue
if (-not $servico) {
    Aviso 'O cloudflared ainda nao esta instalado neste PC.'
    Linha 'Siga o README, parte "CRM no celular" > "Criar o tunel".'
} elseif ($servico.Status -ne 'Running') {
    Aviso "O servico cloudflared esta parado ($($servico.Status))."
    Linha 'Abra o PowerShell como Administrador e rode: Start-Service cloudflared'
} else {
    Ok 'Servico cloudflared rodando.'
}

Titulo '5. Atualizacao automatica'
if ($valores['CRM_AUTOATUALIZAR'] -eq '0') {
    Aviso 'Desligada no .env (CRM_AUTOATUALIZAR=0). Para atualizar: git pull e rode este arquivo de novo.'
} elseif (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Aviso 'O git nao esta instalado: o CRM nao vai se atualizar sozinho.'
} else {
    # o repositorio foi renomeado (claude-code-crm -> vfitcoach-crm): aponta o origin para o nome novo
    $origem = (& git -C $pasta remote get-url origin 2>$null)
    if ($origem -like '*claude-code-crm*') {
        & git -C $pasta remote set-url origin 'https://github.com/UziCelli/vfitcoach-crm.git'
        Ok 'Endereco do GitHub atualizado para UziCelli/vfitcoach-crm.'
    }
    $ramo = (& git -C $pasta rev-parse --abbrev-ref HEAD 2>$null)
    if ($ramo -ne 'main') {
        Aviso "A pasta do CRM esta no ramo '$ramo'. Para se atualizar sozinho, ela precisa estar na main: git checkout main"
    } else {
        Ok 'O CRM confere o GitHub a cada 15 minutos e se atualiza sozinho.'
        Linha 'Ele espera ficar 5 minutos sem ninguem usando. Nao precisa mais de git pull.'
    }
}

Titulo '6. Ligar o CRM agora'
if (CrmRodando) {
    # reinicia para ler o .env e a versao nova (depois de um git pull); /encerrar so funciona pelo proprio PC
    Linha 'O CRM ja estava aberto. Reiniciando para ele ler o .env e a versao nova...'
    try {
        Invoke-WebRequest -Uri 'http://127.0.0.1:8765/encerrar' -Method Post -Headers @{ Origin = 'http://127.0.0.1:8765' } `
            -UseBasicParsing -TimeoutSec 10 | Out-Null
    } catch { }
    for ($n = 0; $n -lt 30 -and (CrmRodando); $n++) { Start-Sleep -Milliseconds 500 }
}
if (CrmRodando) {
    Aviso 'Nao consegui reiniciar o CRM.'
    Linha "Clique em Encerrar no menu do CRM e rode de novo: $comando"
} else {
    & $bat /servidor
    if ($LASTEXITCODE -eq 0) {
        Ok 'CRM ligado em segundo plano.'
    } else {
        Aviso 'O CRM nao ligou. Veja as mensagens acima e o arquivo data\crm-erro.log.'
    }
}

Titulo 'Pronto. Confira:'
Linha '1. No PC: abra http://localhost:8765 (ou o atalho da Area de Trabalho).'
Linha '2. No celular, fora do Wi-Fi: abra https://crm.vfitcoachapp.com e entre com o codigo do e-mail.'
Linha '3. Deixe o PC ligado, na tomada e com a sua conta do Windows aberta.'
Linha '   Pode bloquear a tela (Windows+L). So nao saia da conta.'
Linha '4. Nao clique em Encerrar se for usar o celular. Se clicar, abra o CRM de novo pelo atalho.'
Linha '5. Celular deu erro do Cloudflare (1033 ou 502)? Use a reserva: https://crm-reserva.vfitcoachapp.com'
Linha "Para desfazer: $comando -Desfazer"
Fim 0
