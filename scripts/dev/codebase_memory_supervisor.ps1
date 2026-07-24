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

    $head = (& git --no-optional-locks -C $Root rev-parse HEAD 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($head)) {
        throw "git rev-parse HEAD failed for $Root"
    }

    $statusLines = @(
        & git --no-optional-locks -C $Root status --porcelain -uall 2>$null
    )
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed for $Root"
    }

    $signatureText = [System.Text.StringBuilder]::new()
    [void]$signatureText.AppendLine("HEAD=$head")
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
        return [pscustomobject]@{
            Head = $head
            Signature = (
                [BitConverter]::ToString($hasher.ComputeHash($bytes))
            ).Replace("-", "")
        }
    }
    finally {
        $hasher.Dispose()
    }
}

function Get-IndexedHead {
    param([Parameter(Mandatory = $true)][string]$StatePath)

    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
        return $null
    }
    try {
        $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    }
    catch {
        Write-Warning "Ignoring invalid supervisor state at ${StatePath}: $_"
        return $null
    }
    if ($state.head -notmatch "^[0-9a-fA-F]{40}$") {
        Write-Warning "Ignoring supervisor state with an invalid HEAD at $StatePath"
        return $null
    }
    return $state.head.ToLowerInvariant()
}

function Set-IndexedHead {
    param(
        [Parameter(Mandatory = $true)][string]$StatePath,
        [Parameter(Mandatory = $true)][string]$Head
    )

    $temporaryPath = "$StatePath.tmp"
    @{ head = $Head.ToLowerInvariant() } |
        ConvertTo-Json -Compress |
        Set-Content -LiteralPath $temporaryPath -Encoding utf8
    Move-Item -LiteralPath $temporaryPath -Destination $StatePath -Force
}

function Get-ProjectName {
    param([Parameter(Mandatory = $true)][string]$CacheDirectory)

    $projectDatabases = @(
        Get-ChildItem -LiteralPath $CacheDirectory -Filter "*.db" -File |
            Where-Object { $_.Name -ne "_config.db" }
    )
    if ($projectDatabases.Count -eq 0) {
        return $null
    }
    if ($projectDatabases.Count -ne 1) {
        throw (
            "Expected at most one Codebase Memory project database in " +
            "$CacheDirectory; found $($projectDatabases.Count)"
        )
    }
    return $projectDatabases[0].BaseName
}

function Invoke-Cli {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $Executable @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw (
            "Codebase Memory CLI failed ($exitCode): " +
            ($output -join [Environment]::NewLine)
        )
    }
    return $output
}

function Rebuild-Project {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$CacheDirectory,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedHead
    )

    $projectName = Get-ProjectName -CacheDirectory $CacheDirectory
    Write-Output "full_rebuild_started project=$projectName head=$ExpectedHead"
    if (-not [string]::IsNullOrWhiteSpace($projectName)) {
        $null = Invoke-Cli -Executable $Executable -Arguments @(
            "cli", "delete_project", "--project", $projectName
        )
    }
    $null = Invoke-Cli -Executable $Executable -Arguments @(
        "cli", "index_repository", "--repo-path", $Root, "--mode", "full",
        "--persistence", "false"
    )

    $listOutput = Invoke-Cli -Executable $Executable -Arguments @(
        "cli", "list_projects"
    )
    $projectJson = (
        $listOutput | Where-Object { $_ -match '^\{"projects":' } |
            Select-Object -Last 1
    )
    if ([string]::IsNullOrWhiteSpace($projectJson)) {
        throw "Codebase Memory list_projects returned no JSON project inventory"
    }
    $projects = @((ConvertFrom-Json $projectJson).projects)
    $normalizedRoot = $Root.Replace("\", "/").TrimEnd("/")
    $rebuilt = @(
        $projects | Where-Object {
            $_.root_path.Replace("\", "/").TrimEnd("/") -eq $normalizedRoot
        }
    )
    if ($rebuilt.Count -ne 1) {
        throw "Rebuilt Codebase Memory project could not be resolved by root path"
    }
    if ($rebuilt[0].git.head_sha -ne $ExpectedHead) {
        throw (
            "Rebuilt project HEAD $($rebuilt[0].git.head_sha) does not match " +
            "expected HEAD $ExpectedHead"
        )
    }
    if ([int64]$rebuilt[0].nodes -le 0) {
        throw "Rebuilt Codebase Memory project contains no nodes"
    }
    Write-Output (
        "full_rebuild_completed project=$($rebuilt[0].name) " +
        "head=$ExpectedHead nodes=$($rebuilt[0].nodes) " +
        "edges=$($rebuilt[0].edges)"
    )
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

function Start-CodebaseMemory {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][int]$UiPort
    )

    $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processInfo.FileName = $Executable
    $processInfo.Arguments = "--ui=true --port=$UiPort"
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    $processInfo.RedirectStandardInput = $true
    $managedProcess = [System.Diagnostics.Process]::Start($processInfo)

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

    $managedProcess.StandardInput.WriteLine($initialize)
    $managedProcess.StandardInput.WriteLine($initialized)
    $managedProcess.StandardInput.WriteLine($toolsList)
    $managedProcess.StandardInput.Flush()

    $baseUri = "http://127.0.0.1:$UiPort"
    Wait-UiReady -BaseUri $baseUri -Process $managedProcess
    Wait-IndexIdle -BaseUri $baseUri
    return $managedProcess
}

function Stop-CodebaseMemory {
    param([System.Diagnostics.Process]$ManagedProcess)

    if ($null -eq $ManagedProcess -or $ManagedProcess.HasExited) {
        return
    }
    $ManagedProcess.StandardInput.Close()
    if (-not $ManagedProcess.WaitForExit(5000)) {
        $ManagedProcess.Kill()
        $ManagedProcess.WaitForExit()
    }
}

$resolvedBinary = (Resolve-Path -LiteralPath $BinaryPath).Path
$resolvedRepo = (Resolve-Path -LiteralPath $RepoRoot).Path
$resolvedCache = [System.IO.Path]::GetFullPath($CacheDir)
if (-not (Test-Path -LiteralPath $resolvedCache -PathType Container)) {
    $null = New-Item -ItemType Directory -Path $resolvedCache
}
$statePath = Join-Path $resolvedCache "agenthub-supervisor-state.json"

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

$process = $null
try {
    $baseUri = "http://127.0.0.1:$Port"
    $repositoryState = Get-DirtyStateSignature -Root $resolvedRepo
    $indexedHead = Get-IndexedHead -StatePath $statePath
    if ($indexedHead -ne $repositoryState.Head.ToLowerInvariant()) {
        Rebuild-Project `
            -Executable $resolvedBinary `
            -CacheDirectory $resolvedCache `
            -Root $resolvedRepo `
            -ExpectedHead $repositoryState.Head
        Set-IndexedHead -StatePath $statePath -Head $repositoryState.Head
        $indexedHead = $repositoryState.Head.ToLowerInvariant()
    }
    $process = Start-CodebaseMemory `
        -Executable $resolvedBinary `
        -UiPort $Port
    $lastSignature = $repositoryState.Signature
    $lastHead = $repositoryState.Head
    Write-Output (
        "initial_signature=$lastSignature head=$lastHead indexed_head=$indexedHead"
    )

    while (-not $process.HasExited) {
        Start-Sleep -Seconds $PollSeconds
        $observedState = Get-DirtyStateSignature -Root $resolvedRepo
        if ($observedState.Signature -eq $lastSignature) {
            continue
        }

        try {
            Write-Output (
                "change_detected previous=$lastSignature observed=" +
                "$($observedState.Signature) previous_head=$lastHead " +
                "observed_head=$($observedState.Head)"
            )
            if ($observedState.Head -ne $lastHead) {
                Stop-CodebaseMemory -ManagedProcess $process
                $process = $null
                Rebuild-Project `
                    -Executable $resolvedBinary `
                    -CacheDirectory $resolvedCache `
                    -Root $resolvedRepo `
                    -ExpectedHead $observedState.Head
                Set-IndexedHead -StatePath $statePath -Head $observedState.Head
                $lastHead = $observedState.Head
                $process = Start-CodebaseMemory `
                    -Executable $resolvedBinary `
                    -UiPort $Port
            }
            else {
                Request-Index -BaseUri $baseUri -Root $resolvedRepo
            }
            $lastSignature = $observedState.Signature
            Write-Output "signature_committed=$lastSignature"
        }
        catch {
            Write-Warning "Index request failed and will be retried: $_"
            if ($null -eq $process -or $process.HasExited) {
                $process = Start-CodebaseMemory `
                    -Executable $resolvedBinary `
                    -UiPort $Port
            }
        }
    }

    throw "Codebase Memory exited with code $($process.ExitCode)"
}
finally {
    Stop-CodebaseMemory -ManagedProcess $process

    if ($createdNew) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
