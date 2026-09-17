param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[a-z0-9]{3,24}$")]
    [string]$StorageAccountName,
    [string]$ContainerName = "msexports",
    [string]$StagingRoot = (Join-Path $PSScriptRoot "staging"),
    [string]$ArtifactDirectory,
    [switch]$Replace,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resolvedStagingRoot = (Resolve-Path $StagingRoot).Path
if ([string]::IsNullOrWhiteSpace($ArtifactDirectory)) {
    $latestManifest = Get-ChildItem -Path $resolvedStagingRoot -Filter "manifest.json" -File -Recurse |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latestManifest) {
        throw "No staged manifest.json found under $resolvedStagingRoot."
    }
    $ArtifactDirectory = $latestManifest.DirectoryName
}

$resolvedArtifactDirectory = (Resolve-Path $ArtifactDirectory).Path
$relativeDirectory = [System.IO.Path]::GetRelativePath(
    $resolvedStagingRoot,
    $resolvedArtifactDirectory
).Replace("\", "/")
if ($relativeDirectory.StartsWith("..")) {
    throw "ArtifactDirectory must be inside StagingRoot."
}

$manifestPath = Join-Path $resolvedArtifactDirectory "manifest.json"
if (-not (Test-Path $manifestPath -PathType Leaf)) {
    throw "manifest.json was not found in $resolvedArtifactDirectory."
}

$manifest = try {
    Get-Content -Path $manifestPath -Raw | ConvertFrom-Json
}
catch {
    throw "manifest.json is not valid JSON: $($_.Exception.Message)"
}

$requiredFields = @(
    "manifestVersion",
    "dataset",
    "schemaVersion",
    "loadMode",
    "organization",
    "collectedAtUtc",
    "sourceFiles",
    "exportConfig",
    "runInfo",
    "blobCount",
    "dataRowCount",
    "blobs",
    "target",
    "files",
    "schema"
)
foreach ($field in $requiredFields) {
    if ($manifest.PSObject.Properties.Name -notcontains $field) {
        throw "manifest.json is missing required field '$field'."
    }
}

$expectedDataset = $relativeDirectory.Split("/")[0]
if ($manifest.dataset -ne $expectedDataset) {
    throw "Manifest dataset '$($manifest.dataset)' does not match path '$expectedDataset'."
}
if (@($manifest.files).Count -ne 1) {
    throw "manifest.json must reference exactly one CSV file."
}
$manifestFileName = [string]$manifest.files[0].name
if ([System.IO.Path]::GetFileName($manifestFileName) -ne $manifestFileName) {
    throw "Manifest file name must not contain a directory path."
}
$dataFilePath = Join-Path $resolvedArtifactDirectory $manifestFileName
if (-not (Test-Path $dataFilePath -PathType Leaf)) {
    throw "Manifest CSV file was not found: $dataFilePath"
}
$dataFile = Get-Item -LiteralPath $dataFilePath
if ($manifest.files[0].format -ne "csv") {
    throw "Manifest file format must be 'csv'."
}
foreach ($field in @("type", "dataVersion", "resourceId", "exportName")) {
    if ($manifest.exportConfig.PSObject.Properties.Name -notcontains $field -or
        [string]::IsNullOrWhiteSpace($manifest.exportConfig.$field)) {
        throw "manifest.json exportConfig is missing '$field'."
    }
}
if ($manifest.exportConfig.type -ne $manifest.dataset) {
    throw "Manifest exportConfig.type must match dataset."
}
if ($manifest.exportConfig.dataVersion -ne $manifest.schemaVersion) {
    throw "Manifest exportConfig.dataVersion must match schemaVersion."
}
foreach ($field in @("runId", "startDate")) {
    if ($manifest.runInfo.PSObject.Properties.Name -notcontains $field -or
        [string]::IsNullOrWhiteSpace($manifest.runInfo.$field)) {
        throw "manifest.json runInfo is missing '$field'."
    }
}
if ($manifest.blobCount -ne 1 -or @($manifest.blobs).Count -ne 1) {
    throw "manifest.json must reference exactly one export blob."
}
$expectedBlobName = "$relativeDirectory/$($dataFile.Name)"
if ($manifest.blobs[0].blobName -ne $expectedBlobName) {
    throw "Manifest blob '$($manifest.blobs[0].blobName)' does not match '$expectedBlobName'."
}
if ($manifest.dataRowCount -ne $manifest.files[0].rowCount) {
    throw "Manifest dataRowCount must match files[0].rowCount."
}
foreach ($field in @("database", "rawTable", "parquetMapping")) {
    if ($manifest.target.PSObject.Properties.Name -notcontains $field -or
        [string]::IsNullOrWhiteSpace($manifest.target.$field)) {
        throw "manifest.json target is missing '$field'."
    }
}
if (@($manifest.schema.columns).Count -eq 0) {
    throw "manifest.json schema must contain at least one column."
}
if ($manifest.schema.sha256 -notmatch "^[0-9a-f]{64}$") {
    throw "manifest.json schema.sha256 must be a lowercase SHA-256 value."
}

Write-Host "Validated manifest: $($manifest.dataset) $($manifest.schemaVersion) -> $($manifest.target.database).$($manifest.target.rawTable)"
if ($ValidateOnly) {
    return
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI (az) is required."
}

& az account show --only-show-errors 1>$null
if ($LASTEXITCODE -ne 0) {
    throw "Azure CLI is not authenticated."
}

$blobPrefix = "$relativeDirectory/"
$existingBlobs = @(
    & az storage blob list `
        --account-name $StorageAccountName `
        --container-name $ContainerName `
        --prefix $blobPrefix `
        --auth-mode login `
        --only-show-errors `
        --query "[].name" `
        --output tsv
)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to list blobs under $blobPrefix. Check Storage Blob Data permissions."
}

if ($existingBlobs.Count -gt 0 -and -not $Replace) {
    throw "The target path already contains blobs. Use -Replace to replace the full dataset partition."
}

if ($Replace) {
    foreach ($blobName in $existingBlobs) {
        & az storage blob delete `
            --account-name $StorageAccountName `
            --container-name $ContainerName `
            --name $blobName `
            --auth-mode login `
            --only-show-errors 1>$null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to delete existing blob $blobName."
        }
    }
}

$dataBlobName = "$blobPrefix$($dataFile.Name)"
& az storage blob upload `
    --account-name $StorageAccountName `
    --container-name $ContainerName `
    --name $dataBlobName `
    --file $dataFile.FullName `
    --auth-mode login `
    --overwrite false `
    --only-show-errors 1>$null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upload $dataBlobName."
}

$manifestBlobName = "$blobPrefix`manifest.json"
& az storage blob upload `
    --account-name $StorageAccountName `
    --container-name $ContainerName `
    --name $manifestBlobName `
    --file $manifestPath `
    --auth-mode login `
    --overwrite false `
    --only-show-errors 1>$null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upload $manifestBlobName."
}

Write-Host "Published CSV: $dataBlobName"
Write-Host "Triggered ingestion: $manifestBlobName"