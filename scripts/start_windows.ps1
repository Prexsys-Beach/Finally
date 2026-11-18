# Start FinAlly in Docker. Safe to run repeatedly.
# Usage: scripts\start_windows.ps1 [-Build] [-NoOpen]
param(
    [switch]$Build,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

$Image = "finally"
$Container = "finally"
$Volume = "finally-data"
$Url = "http://localhost:8000"
$Root = Split-Path -Parent $PSScriptRoot

function Test-Health {
    try {
        Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-Running {
    $state = (& docker inspect -f "{{.State.Running}}" $Container 2>$null)
    return $state -eq "true"
}

function Remove-Container {
    $ErrorActionPreference = "Continue"
    & docker rm -f $Container 2>$null | Out-Null
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker isn't installed. Get it from https://www.docker.com/products/docker-desktop/"
}
function Test-Docker {
    $ErrorActionPreference = "Continue"
    & docker info 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-Docker)) {
    $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktop) {
        Start-Process $desktop
        Write-Host -NoNewline "Starting Docker Desktop"
        for ($i = 0; $i -lt 120; $i++) {
            if (Test-Docker) { break }
            Write-Host -NoNewline "."
            Start-Sleep -Seconds 1
        }
        Write-Host ""
    }
    if (-not (Test-Docker)) {
        Write-Error "Docker isn't running. Start Docker Desktop, then run this again."
    }
}

Set-Location $Root
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Add your OPENROUTER_API_KEY to enable AI chat."
}

$ErrorActionPreference = "Continue"
& docker image inspect $Image 2>$null | Out-Null
$imageExists = $LASTEXITCODE -eq 0
$ErrorActionPreference = "Stop"

if ($Build -or -not $imageExists) {
    Write-Host "Building the $Image image. The first build takes a few minutes."
    & docker build -t $Image .
    if ($LASTEXITCODE -ne 0) { Write-Error "The image build failed." }
    Remove-Container
}

if (Test-Running) {
    Write-Host "FinAlly is already running at $Url"
    Write-Host "To load code or .env changes: scripts\start_windows.ps1 -Build"
} else {
    Remove-Container
    & docker run -d --name $Container --env-file .env -v "${Volume}:/app/db" -p 8000:8000 $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Error "The container failed to start." }

    Write-Host -NoNewline "Starting"
    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Health) { $healthy = $true; break }
        if (-not (Test-Running)) {
            Write-Host ""
            & docker logs --tail 30 $Container
            Write-Error "FinAlly stopped during startup."
        }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 1
    }
    Write-Host ""
    if (-not $healthy) { Write-Error "FinAlly didn't respond in time. Check: docker logs $Container" }
    Write-Host "FinAlly is running at $Url"
}

Write-Host "Stop it with scripts\stop_windows.ps1"
if (-not $NoOpen) { Start-Process $Url }
