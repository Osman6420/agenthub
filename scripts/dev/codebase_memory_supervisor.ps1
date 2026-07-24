[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BinaryPath,

    [Parameter(Mandatory = $true)]
    [string]$CacheDir,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [ValidateRange(1, 65535)]
    [int]$Port = 9749,

    [ValidateRange(2, 300)]
    [int]$PollSeconds = 6
)

$ErrorActionPreference = "Stop"

function Get-DirtyStateSignature {
    param([Parameter(Mandatory = $true)][string]$Root)

    $statusLines = @(
        & git --no-optional-locks -C $Root status --porcelain -uall 2>$null
    )
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed for $Root"
    }

    $signatureText = [System.Text.StringBuilder]::new()
    foreach ($line in $statusLines) {
        if ($line.Length -lt 4) {
            continue
        }

        [void]$signatureText.AppendLine($line)
        $relativePath = $line.Substring(3).Trim('"')
        if ($relativePath -match " -> ") {
            $relativePath = ($relativePath -split " -> ")[-1].Trim('"')
        }

        $absolutePath = Join-Path $Root $relativePath
        $item = Get-Item -LiteralPath $absolutePath -ErrorAction SilentlyContinue
        if ($null -eq $item) {
            [void]$signatureText.AppendLine("missing")
            continue
        }

        [void]$signatureText.AppendLine(
            "$($item.Length)|$($item.LastWriteTimeUtc.Ticks)"
        )
    }

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($signatureText.ToString())
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($hasher.ComputeHash($bytes))).Replace(
            "-",
            ""
        )
    }
    finally {
        $hasher.Dispose()
    }
}

function Wait-UiReady {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUri,
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($Process.HasExited) {
            throw "Codebase Memory exited with code $($Process.ExitCode)"
        }

        try {
            $response = Invoke-WebRequest `
                -UseBasicParsing `
                -TimeoutSec 3 `
                -Uri "$BaseUri/"
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }

    throw "Codebase Memory UI did not become ready at $BaseUri"
}

function Wait-IndexIdle {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUri,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $statusResponse = Invoke-RestMethod `
                -TimeoutSec 5 `
                -Uri "$BaseUri/api/index-status"
        }
        catch {
            Start-Sleep -Seconds 1
            continue
        }
        if ($statusResponse -is [string]) {
            if ($statusResponse -match '"status"\s*:\s*"error"') {
                throw "Codebase Memory indexing failed: $statusResponse"
            }
            if ($statusResponse -match '"status"\s*:\s*"indexing"') {
                Start-Sleep -Seconds 1
                continue
            }
            return
        }
        else {
            $statuses = @($statusResponse)
        }
        $errors = @($statuses | Where-Object { $_.status -eq "error" })
        if ($errors.Count -gt 0) {
            throw "Codebase Memory indexing failed: $($errors.error -join '; ')"
        }

        $active = @($statuses | Where-Object { $_.status -eq "indexing" })
        if ($active.Count -eq 0) {
            return
        }

        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    throw "Codebase Memory indexing did not become idle"
}

function Request-Index {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUri,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $payload = @{ root_path = $Root } | ConvertTo-Json
    $null = Invoke-WebRequest `
        -UseBasicParsing `
        -TimeoutSec 10 `
        -Method Post `
        -ContentType "application/json" `
        -Body $payload `
        -Uri "$BaseUri/api/index"
    Wait-IndexIdle -BaseUri $BaseUri
}

$resolvedBinary = (Resolve-Path -LiteralPath $BinaryPath).Path
$resolvedRepo = (Resolve-Path -LiteralPath $RepoRoot).Path
$resolvedCache = [System.IO.Path]::GetFullPath($CacheDir)
if (-not (Test-Path -LiteralPath $resolvedCache -PathType Container)) {
    $null = New-Item -ItemType Directory -Path $resolvedCache
}

$createdNew = $false
$mutex = [System.Threading.Mutex]::new(
    $true,
    "Local\AgentHubCodebaseMemorySupervisor",
    [ref]$createdNew
)
if (-not $createdNew) {
    $mutex.Dispose()
    exit 0
}

$env:CBM_ALLOWED_ROOT = $resolvedRepo
$env:CBM_CACHE_DIR = $resolvedCache
$env:CBM_DIAGNOSTICS = "false"

$processInfo = [System.Diagnostics.ProcessStartInfo]::new()
$processInfo.FileName = $resolvedBinary
$processInfo.Arguments = "--ui=true --port=$Port"
$processInfo.UseShellExecute = $false
$processInfo.CreateNoWindow = $true
$processInfo.RedirectStandardInput = $true

$process = $null
try {
    $process = [System.Diagnostics.Process]::Start($processInfo)
    $initialize = @{
        jsonrpc = "2.0"
        id = 1
        method = "initialize"
        params = @{
            protocolVersion = "2024-11-05"
            capabilities = @{}
            clientInfo = @{
                name = "agenthub-codebase-memory-supervisor"
                version = "1.0"
            }
        }
    } | ConvertTo-Json -Compress -Depth 5
    $initialized = @{
        jsonrpc = "2.0"
        method = "notifications/initialized"
        params = @{}
    } | ConvertTo-Json -Compress
    $toolsList = @{
        jsonrpc = "2.0"
        id = 2
        method = "tools/list"
        params = @{}
    } | ConvertTo-Json -Compress

    $process.StandardInput.WriteLine($initialize)
    $process.StandardInput.WriteLine($initialized)
    $process.StandardInput.WriteLine($toolsList)
    $process.StandardInput.Flush()

    $baseUri = "http://127.0.0.1:$Port"
    Wait-UiReady -BaseUri $baseUri -Process $process
    Wait-IndexIdle -BaseUri $baseUri
    $lastSignature = Get-DirtyStateSignature -Root $resolvedRepo
    Write-Output "initial_signature=$lastSignature"

    while (-not $process.HasExited) {
        Start-Sleep -Seconds $PollSeconds
        $observedSignature = Get-DirtyStateSignature -Root $resolvedRepo
        if ($observedSignature -eq $lastSignature) {
            continue
        }

        try {
            Write-Output (
                "change_detected previous=$lastSignature observed=" +
                $observedSignature
            )
            Request-Index -BaseUri $baseUri -Root $resolvedRepo
            $lastSignature = $observedSignature
            Write-Output "signature_committed=$lastSignature"
        }
        catch {
            Write-Warning "Index request failed and will be retried: $_"
        }
    }

    throw "Codebase Memory exited with code $($process.ExitCode)"
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(5000)) {
            $process.Kill()
        }
    }

    if ($createdNew) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
