[CmdletBinding()]
param(
    [string]$OutputPath,
    [switch]$IncludeUntracked,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$RepositoryRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))

function Invoke-GitLines {
    param([Parameter(Mandatory)] [string[]]$Arguments)

    $result = & git -C $RepositoryRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($Arguments -join ' ')"
    }
    return @($result | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Test-ExcludedPath {
    param([Parameter(Mandatory)] [string]$RelativePath)

    $normalized = $RelativePath.Replace('\', '/')
    $lower = $normalized.ToLowerInvariant()
    $fileName = [System.IO.Path]::GetFileName($lower)

    $excludedPrefixes = @(
        '.git/', '.venv/', 'venv/', 'env/', 'dist/', 'build/',
        'frontend/node_modules/', 'frontend/dist/', 'apps/builder/static/builder/',
        '__pycache__/', '.pytest_cache/', '.mypy_cache/', '.ruff_cache/',
        'staticfiles/', 'media/', '.runtime/', '.codebase-memory/', '.worktrees/', '.tmp/'
    )
    foreach ($prefix in $excludedPrefixes) {
        if ($lower.StartsWith($prefix, [System.StringComparison]::Ordinal)) {
            return $true
        }
    }

    if ($lower -match '(^|/)__pycache__/') { return $true }
    if ($fileName -eq '.env' -or ($fileName.StartsWith('.env.') -and $fileName -ne '.env.example')) { return $true }
    if ($lower -match '(^|/)deploy/openshift/install/[^/]+\.env$') { return $true }
    if ($lower -match '(^|/)agenthub-values[^/]*\.ya?ml$') { return $true }
    if ($lower -match '\.(pem|key|p12|pfx|jks|sqlite3)$') { return $true }
    if ($lower -eq 'examples/external-consumer-demo/credentials.local.json') { return $true }
    if ($lower -match '(^|/)(agenthub-openshift\.tar\.gz|agenthub-transfer-[^/]+\.zip)$') { return $true }
    return $false
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Required command 'git' was not found on PATH."
}

$gitRoot = (& git -C $RepositoryRoot rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or [System.IO.Path]::GetFullPath($gitRoot) -ne $RepositoryRoot) {
    throw "The script must run from its AgentHub Git checkout: $RepositoryRoot"
}

$commit = (& git -C $RepositoryRoot rev-parse --short=12 HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve the source commit.' }
$branch = (& git -C $RepositoryRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve the source branch.' }
$status = @(& git -C $RepositoryRoot status --porcelain --untracked-files=normal)
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect the working tree.' }
$dirty = $status.Count -gt 0

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $dateStamp = Get-Date -Format 'yyyyMMdd'
    $dirtySuffix = if ($dirty) { '-working-tree' } else { '' }
    $OutputPath = Join-Path $RepositoryRoot "dist\agenthub-source-$dateStamp-$commit$dirtySuffix.zip"
}
elseif (-not [System.IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath = Join-Path $RepositoryRoot $OutputPath
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$repositoryPrefix = $RepositoryRoot + [System.IO.Path]::DirectorySeparatorChar
$distPrefix = [System.IO.Path]::GetFullPath((Join-Path $RepositoryRoot 'dist')) + [System.IO.Path]::DirectorySeparatorChar
if ($OutputPath.StartsWith($repositoryPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
    -not $OutputPath.StartsWith($distPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'An output inside the repository must be below dist/ so it cannot enter a later source package.'
}

if (Test-Path -LiteralPath $OutputPath) {
    if (-not $Force) {
        throw "Output already exists: $OutputPath. Choose another path or pass -Force."
    }
    Remove-Item -LiteralPath $OutputPath -Force
}

$files = [System.Collections.Generic.List[string]]::new()
foreach ($path in (Invoke-GitLines -Arguments @('ls-files', '--cached'))) {
    $files.Add($path.Replace('\', '/'))
}
if ($IncludeUntracked) {
    foreach ($path in (Invoke-GitLines -Arguments @('ls-files', '--others', '--exclude-standard'))) {
        $files.Add($path.Replace('\', '/'))
    }
}

$files = @($files | Sort-Object -Unique | Where-Object { -not (Test-ExcludedPath -RelativePath $_) })
if ($files.Count -eq 0) { throw 'No eligible source files were found.' }

$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$stagingRoot = Join-Path $tempBase ("agenthub-source-package-" + [System.Guid]::NewGuid().ToString('N'))
$stagingRoot = [System.IO.Path]::GetFullPath($stagingRoot)
if (-not $stagingRoot.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Refusing to stage outside the operating-system temporary directory.'
}
$packageRoot = Join-Path $stagingRoot 'agenthub'

try {
    New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
    $manifestLines = [System.Collections.Generic.List[string]]::new()

    foreach ($relativePath in $files) {
        if ([System.IO.Path]::IsPathRooted($relativePath) -or $relativePath.Split('/') -contains '..') {
            throw "Unsafe repository path: $relativePath"
        }
        $sourcePath = [System.IO.Path]::GetFullPath((Join-Path $RepositoryRoot $relativePath))
        if (-not $sourcePath.StartsWith(($RepositoryRoot + [System.IO.Path]::DirectorySeparatorChar), [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Repository path escapes the checkout: $relativePath"
        }
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Source file disappeared during packaging: $relativePath"
        }
        $sourceItem = Get-Item -LiteralPath $sourcePath -Force
        if (($sourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Symbolic links and reparse points are not packaged: $relativePath"
        }
        $destinationPath = Join-Path $packageRoot $relativePath
        $destinationDirectory = Split-Path -Parent $destinationPath
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destinationPath).Hash.ToLowerInvariant()
        $manifestLines.Add("$hash  agenthub/$relativePath")
    }

    $utcTimestamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    $packageReadme = @"
# AgentHub source package

Created: $utcTimestamp
Source commit: $commit
Source branch: $branch
Working tree dirty: $dirty
Non-ignored untracked files included: $($IncludeUntracked.IsPresent)

Start with agenthub/docs/operations/openshift-helm-installation.md for the preferred OpenShift Helm installation path.

This package contains source and documentation only. It intentionally excludes secrets, environment-specific values, Git history, container images, databases, object-store data, dependencies, caches, and generated build output. Supply secrets separately through the approved deployment workflow.
"@
    Set-Content -LiteralPath (Join-Path $stagingRoot 'PACKAGE-README.md') -Value $packageReadme -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $stagingRoot 'PACKAGE-MANIFEST.sha256') -Value ($manifestLines -join "`n") -Encoding UTF8

    $outputDirectory = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $stagingRoot,
        $OutputPath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}

$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath).Hash.ToLowerInvariant()
Write-Output "Archive: $OutputPath"
Write-Output "Repository files: $($files.Count)"
Write-Output "Source commit: $commit"
Write-Output "Working tree dirty: $dirty"
Write-Output "SHA256: $archiveHash"
