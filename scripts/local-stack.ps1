[CmdletBinding()]
param(
    [ValidateSet('Update', 'Fresh', 'Status', 'Stop', 'Logs')]
    [string]$Action = 'Update',
    [ValidateSet('web', 'worker-runtime', 'worker-ingestion', 'worker-eval', 'beat', 'migrate', 'postgres', 'redis', 'minio')]
    [string]$Service = 'web',
    [ValidateRange(10, 600)]
    [int]$HealthTimeoutSeconds = 120,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $RepositoryRoot 'deploy\compose\docker-compose.yml'
$HealthUri = 'http://127.0.0.1:8000/v1/health/live'
$ApplicationServices = @('web', 'worker-runtime', 'worker-ingestion', 'worker-eval', 'beat')

function Invoke-Checked {
    param([Parameter(Mandatory)] [string]$FilePath, [Parameter(Mandatory)] [string[]]$ArgumentList)
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($ArgumentList -join ' ')"
    }
}

function Assert-Command {
    param([Parameter(Mandatory)] [string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH. See docs/operations/local-development-stack.md."
    }
}

function Invoke-Compose {
    param([Parameter(Mandatory)] [string[]]$Arguments)
    Invoke-Checked -FilePath 'docker' -ArgumentList (@('compose', '-f', $ComposeFile) + $Arguments)
}

function Show-Status {
    Invoke-Compose -Arguments @('ps')
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri $HealthUri
        Write-Host "Liveness: HTTP $($response.StatusCode) ($HealthUri)" -ForegroundColor Green
    }
    catch {
        Write-Warning "Liveness is unavailable at $HealthUri. This does not by itself mean infrastructure is down."
    }
}

function Wait-ForLiveness {
    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri $HealthUri
            if ($response.StatusCode -eq 200) {
                Write-Host "AgentHub is ready: $HealthUri" -ForegroundColor Green
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    Write-Warning 'Startup did not become healthy. Current Compose state and the last 100 web log lines follow.'
    Invoke-Compose -Arguments @('ps')
    Invoke-Compose -Arguments @('logs', '--tail', '100', 'web')
    throw "AgentHub did not pass liveness within $HealthTimeoutSeconds seconds."
}

function Build-Frontend {
    Assert-Command -Name 'node'
    Assert-Command -Name 'npm'
    $lockPath = Join-Path $RepositoryRoot 'frontend\package-lock.json'
    $fingerprintPath = Join-Path $RepositoryRoot 'frontend\node_modules\.agenthub-dependency-fingerprint'
    $nodeModulesPath = Join-Path $RepositoryRoot 'frontend\node_modules'

    $nodeVersion = (& node --version).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Failed to read the Node.js version.' }
    $npmVersion = (& npm --version).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Failed to read the npm version.' }
    $lockHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $lockPath).Hash
    $dependencyFingerprint = "$lockHash|$nodeVersion|$npmVersion"
    $installedFingerprint = if (Test-Path -LiteralPath $fingerprintPath) {
        (Get-Content -Raw -LiteralPath $fingerprintPath).Trim()
    }
    else { '' }

    if ((Test-Path -LiteralPath $nodeModulesPath) -and $installedFingerprint -eq $dependencyFingerprint) {
        Write-Host 'Frontend dependency lock and toolchain are unchanged; skipping npm ci.'
    }
    else {
        Write-Host 'Frontend dependency lock or toolchain changed; installing locked dependencies...'
        Invoke-Checked -FilePath 'npm' -ArgumentList @('--prefix', 'frontend', 'ci')
        Set-Content -NoNewline -LiteralPath $fingerprintPath -Value $dependencyFingerprint
    }
    Write-Host 'Building the workflow-builder frontend...'
    Invoke-Checked -FilePath 'npm' -ArgumentList @('--prefix', 'frontend', 'run', 'build')
}

function Build-CurrentSource {
    Build-Frontend
    Write-Host 'Building the current application image...'
    Invoke-Compose -Arguments @('build')
}

function Start-Stack {
    Write-Host 'Starting infrastructure...'
    Invoke-Compose -Arguments @('up', '-d', '--remove-orphans', 'postgres', 'redis', 'minio')
    Write-Host 'Applying forward database migrations...'
    Invoke-Compose -Arguments @('run', '--rm', 'migrate')
    Write-Host 'Starting web, workers, and scheduler...'
    Invoke-Compose -Arguments (@('up', '-d', '--no-deps', '--remove-orphans') + $ApplicationServices)
    Wait-ForLiveness
    Show-Status
}

Push-Location $RepositoryRoot
try {
    Assert-Command -Name 'docker'
    Invoke-Compose -Arguments @('config', '--quiet')

    switch ($Action) {
        'Status' { Show-Status }
        'Logs' { Invoke-Compose -Arguments @('logs', '--tail', '100', $Service) }
        'Stop' {
            Write-Host 'Stopping the local stack. Named volumes and local data will be preserved.'
            Invoke-Compose -Arguments @('down', '--remove-orphans')
        }
        'Fresh' {
            Build-CurrentSource
            if ($Force) {
                Write-Host 'DANGER: -Force bypasses confirmation and permanently deletes all local PostgreSQL and MinIO Compose data.' -ForegroundColor Red
                Write-Host 'This script cannot recover the data. Use -Force only in controlled disposable automation.' -ForegroundColor Red
            }
            else {
                Write-Warning 'Fresh permanently deletes this project local PostgreSQL and MinIO Compose volumes.'
                $confirmation = Read-Host 'Type FRESH to continue'
                if ($confirmation -cne 'FRESH') {
                    throw 'Fresh startup cancelled; no data was deleted.'
                }
            }
            Write-Host 'Removing the existing local stack and named volumes...'
            Invoke-Compose -Arguments @('down', '--volumes', '--remove-orphans')
            Start-Stack
        }
        'Update' {
            Write-Host 'Updating the local stack while preserving PostgreSQL and MinIO volumes...'
            Build-CurrentSource
            Start-Stack
        }
    }
}
finally {
    Pop-Location
}
