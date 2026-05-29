param(
    [switch]$InitDb,
    [switch]$SkipOllama,
    [switch]$SkipBrowser,
    [switch]$SkipBackend
)

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$BackendDir = Join-Path $ProjectDir "deepseek_agent\llm_backend"
$Python = Join-Path $ProjectDir "deepseek_agent\.venv\python.exe"
$RunPy = Join-Path $BackendDir "run.py"
$InitDbPy = Join-Path $BackendDir "scripts\init_db.py"
$StartServicesPy = Join-Path $ProjectDir "local_services\start_all_services.py"
$CheckServicesPs1 = Join-Path $ProjectDir "local_services\check_services.ps1"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ">>> $Message"
}

if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python"
}

if (-not (Test-Path $RunPy)) {
    throw "Backend entry not found: $RunPy"
}

Write-Step "Starting MySQL, Redis, and Neo4j"
& $Python $StartServicesPy

Write-Step "Checking MySQL, Redis, and Neo4j"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $CheckServicesPs1

if (-not $SkipOllama) {
    Write-Step "Checking Ollama"
    $Ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $Ollama) {
        throw "Ollama command not found. Install Ollama or run this script with -SkipOllama."
    }

    $OllamaListening = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 11434 -ErrorAction SilentlyContinue
    if (-not $OllamaListening) {
        Write-Host "Ollama is not listening on 127.0.0.1:11434, starting it in the background..."
        Start-Process -FilePath $Ollama.Source -ArgumentList "serve" -WindowStyle Hidden

        $OllamaReady = $false
        for ($i = 0; $i -lt 30; $i++) {
            $OllamaListening = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 11434 -ErrorAction SilentlyContinue
            if ($OllamaListening) {
                $OllamaReady = $true
                break
            }
            Start-Sleep -Seconds 1
        }

        if (-not $OllamaReady) {
            throw "Ollama did not become ready on 127.0.0.1:11434"
        }
    }

    $Models = (& $Ollama.Source list) -join "`n"
    foreach ($Model in @("gemma3:4b", "bge-m3")) {
        if ($Models -notmatch [regex]::Escape($Model)) {
            Write-Host "Required Ollama model is missing: $Model"
            Write-Host "Run: ollama pull $Model"
        }
    }
}

if ($InitDb) {
    Write-Step "Initializing MySQL tables"
    Write-Host "Warning: init_db.py drops existing tables before recreating them."
    & $Python $InitDbPy
}

if (-not $SkipBackend) {
    if (-not $SkipBrowser) {
        Write-Step "Browser will open after the backend starts"
        Start-Job -ScriptBlock {
            Start-Sleep -Seconds 5
            Start-Process "http://127.0.0.1:8000"
        } | Out-Null
    }

    Write-Step "Starting backend and static frontend"
    Write-Host "Frontend: http://127.0.0.1:8000"
    Write-Host "API docs: http://127.0.0.1:8000/docs"
    Write-Host "Press Ctrl+C to stop the backend process in this terminal."
    & $Python $RunPy
} elseif (-not $SkipBrowser) {
    Write-Step "Opening browser"
    Start-Process "http://127.0.0.1:8000"
}
