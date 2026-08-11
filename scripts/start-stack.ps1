$ErrorActionPreference = "Stop"

function Get-DockerCliPath {
    $candidate = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (Test-Path $candidate) {
        return $candidate
    }

    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    return $null
}

Write-Host "[1/5] Checking Docker CLI..." -ForegroundColor Cyan
${docker} = Get-DockerCliPath
if (-not ${docker}) {
    Write-Error "Docker CLI not found. Install Docker Desktop and restart this terminal."
}

Write-Host "[2/5] Checking Docker engine..." -ForegroundColor Cyan
${service} = Get-Service com.docker.service -ErrorAction SilentlyContinue
if (${service} -and ${service}.Status -ne "Running") {
    Write-Error "Docker Desktop Service is not running. Start Docker Desktop as Administrator and wait until engine status is healthy."
}

& ${docker} info | Out-Null

Set-Location "$PSScriptRoot\.."

Write-Host "[3/5] Ensuring .env exists..." -ForegroundColor Cyan
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}

Write-Host "[4/5] Building and starting services..." -ForegroundColor Cyan
& ${docker} compose up -d --build

Write-Host "[5/5] Confirming service status..." -ForegroundColor Cyan
& ${docker} compose ps

Write-Host "Stack startup completed." -ForegroundColor Green
