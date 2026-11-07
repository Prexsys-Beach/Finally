# Stop FinAlly. Safe to run repeatedly. Your data stays in the Docker volume.
$Container = "finally"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker isn't installed, so FinAlly isn't running."
    exit 0
}

& docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker isn't running, so FinAlly isn't either."
    exit 0
}

& docker inspect $Container 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    & docker stop $Container | Out-Null
    & docker rm $Container | Out-Null
    Write-Host "FinAlly stopped. Your portfolio is saved."
} else {
    Write-Host "FinAlly isn't running."
}
