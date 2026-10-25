# Instalador do juris-oficial (Windows / PowerShell).
# Uso: clique com o botão direito > "Executar com o PowerShell", ou:
#   powershell -ExecutionPolicy Bypass -File .\instalar.ps1
$ErrorActionPreference = "Stop"
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$servidor = Join-Path $pasta "servidor.py"
Write-Host "== juris-oficial: instalação ==" -ForegroundColor Cyan

# 1. Python 3.10 ou superior
$python = $null
foreach ($c in @("python", "py")) {
    try {
        $v = & $c -c "import sys; print(sys.version_info >= (3, 10), sys.executable)" 2>$null
        if ($v -and $v.StartsWith("True")) { $python = $v.Split(" ", 2)[1].Trim(); break }
    } catch {}
}
if (-not $python) {
    Write-Host "Python 3.10+ não encontrado. Instale em https://www.python.org/downloads/ (marque 'Add python.exe to PATH') e rode de novo." -ForegroundColor Red
    exit 1
}
Write-Host "Python: $python"

# 2. Dependências
& $python -m pip install --quiet --disable-pip-version-check -r (Join-Path $pasta "requirements.txt")
if ($LASTEXITCODE -ne 0) { Write-Host "Falha ao instalar as dependências." -ForegroundColor Red; exit 1 }
# O teste do passo 5 não carrega o servidor: sem esta checagem, um SDK incompatível
# (mcp 2.x removeu o FastMCP) ou uma dependência faltando só aparece no Claude como
# "Failed to connect". São os mesmos imports do topo do servidor.py.
& $python -c "import sys; sys.path.insert(0, sys.argv[1]); from mcp.server.fastmcp import FastMCP; from juris_oficial import bnp, diagnostico, fontes; from juris_oficial.comum import markdown" $pasta
if ($LASTEXITCODE -ne 0) { Write-Host "O servidor não importa (ver o erro acima). Se for o FastMCP, o 'mcp' precisa ser 1.x: $python -m pip install `"mcp>=1.2,<2`"" -ForegroundColor Red; exit 1 }
Write-Host "Dependências instaladas."

# 3. Navegador (STJ e STF exigem Chrome ou Edge)
$nav = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
         "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
         "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
         "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
         "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($nav) { Write-Host "Navegador para STJ/STF: $nav" }
else { Write-Host "AVISO: Chrome/Edge não encontrado – STJ e STF não vão funcionar." -ForegroundColor Yellow }

# 4. Registro no Claude Code (escopo do usuário: vale em qualquer pasta)
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
    & claude mcp remove juris-oficial --scope user 2>$null | Out-Null
    & claude mcp add juris-oficial --scope user -- $python $servidor
    Write-Host "Registrado no Claude Code (reinicie a sessão para carregar)." -ForegroundColor Green
} else {
    Write-Host "Claude Code não encontrado. Para o Claude Desktop, acrescente em %APPDATA%\Claude\claude_desktop_config.json:" -ForegroundColor Yellow
    $cfg = @{ mcpServers = @{ "juris-oficial" = @{ command = $python; args = @($servidor) } } } | ConvertTo-Json -Depth 5
    Write-Host $cfg
}

# 5. Teste real de todas as fontes
Write-Host "`n== Testando as fontes (1 a 2 minutos) ==" -ForegroundColor Cyan
Push-Location $pasta
& $python -X utf8 -m juris_oficial.diagnostico
Pop-Location
Write-Host "`nPronto. No Claude, peça por exemplo: 'pesquise no STJ e no TRF1 acordo de não persecução penal e retroatividade'."
