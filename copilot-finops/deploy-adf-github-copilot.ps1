param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[0-9a-fA-F-]{36}$")]
    [string]$SubscriptionId,
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$ResourceGroupName,
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$FactoryName,
    [Parameter(Mandatory)]
    [ValidatePattern("^[a-z0-9]{3,24}$")]
    [string]$StorageAccountName,
    [string]$ConfigContainerName = "config",
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$schemaDirectory = Join-Path $PSScriptRoot "config/schemas"
$schemaFiles = @(
    "githubcopilot_1.0.json",
    "githubcopilotfocus_1.0.json"
)

foreach ($schemaFile in $schemaFiles) {
    $schemaPath = Join-Path $schemaDirectory $schemaFile
    if (-not (Test-Path $schemaPath -PathType Leaf)) {
        throw "Schema mapping was not found: $schemaPath"
    }

    $mapping = Get-Content -Path $schemaPath -Raw | ConvertFrom-Json
    if ($mapping.translator.type -ne "TabularTranslator" -or
        @($mapping.translator.mappings).Count -eq 0) {
        throw "Schema mapping is invalid: $schemaPath"
    }
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI (az) is required."
}

& az account set --subscription $SubscriptionId --only-show-errors
if ($LASTEXITCODE -ne 0) {
    throw "Unable to select Azure subscription $SubscriptionId."
}

$pipelineName = "msexports_ExecuteETL"
$pipelineUrl = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroupName/providers/Microsoft.DataFactory/factories/$FactoryName/pipelines/$pipelineName`?api-version=2018-06-01"
$pipeline = & az rest --method get --url $pipelineUrl --only-show-errors --output json |
    ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read ADF pipeline $pipelineName."
}

$setHubDataset = @($pipeline.properties.activities | Where-Object name -eq "Set Hub Dataset")
if ($setHubDataset.Count -ne 1) {
    throw "Expected one 'Set Hub Dataset' activity in $pipelineName."
}

$currentExpression = $setHubDataset[0].typeProperties.value.value

function Add-DatasetAlias {
    param(
        [Parameter(Mandatory)]
        [string]$Expression,
        [Parameter(Mandatory)]
        [string]$SourceName,
        [Parameter(Mandatory)]
        [string]$TargetName
    )

    $condition = "equals(toLower(variables('exportDatasetType')), '$SourceName')"
    if ($Expression.Contains($condition)) {
        return $Expression
    }

    $fallback = "toLower(variables('exportDatasetType'))"
    $fallbackIndex = $Expression.LastIndexOf($fallback, [System.StringComparison]::Ordinal)
    if ($fallbackIndex -lt 0) {
        throw "The ADF routing expression does not contain the expected dataset fallback."
    }

    $replacement = "if($condition, '$TargetName', $fallback)"
    return $Expression.Substring(0, $fallbackIndex) + $replacement +
        $Expression.Substring($fallbackIndex + $fallback.Length)
}

$desiredExpression = Add-DatasetAlias -Expression $currentExpression `
    -SourceName "githubcopilot" -TargetName "GitHubCopilot"
$desiredExpression = Add-DatasetAlias -Expression $desiredExpression `
    -SourceName "githubcopilotfocus" -TargetName "GitHubCopilotFocus"

$openParentheses = ($desiredExpression.ToCharArray() | Where-Object { $_ -eq '(' }).Count
$closeParentheses = ($desiredExpression.ToCharArray() | Where-Object { $_ -eq ')' }).Count
if ($openParentheses -ne $closeParentheses) {
    throw "The generated ADF routing expression has unbalanced parentheses."
}

Write-Host "Validated schema mappings: $($schemaFiles.Count)"
Write-Host "ADF routing state: $(if ($currentExpression -eq $desiredExpression) { 'configured' } else { 'pending' })"
if ($ValidateOnly) {
    return
}

foreach ($schemaFile in $schemaFiles) {
    & az storage blob upload `
        --subscription $SubscriptionId `
        --account-name $StorageAccountName `
        --container-name $ConfigContainerName `
        --name "schemas/$schemaFile" `
        --file (Join-Path $schemaDirectory $schemaFile) `
        --auth-mode login `
        --overwrite true `
        --only-show-errors `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upload schema mapping $schemaFile."
    }
}

if ($currentExpression -ne $desiredExpression) {
    $setHubDataset[0].typeProperties.value.value = $desiredExpression
    $requestBody = @{ properties = $pipeline.properties } | ConvertTo-Json -Depth 100
    $requestPath = Join-Path ([System.IO.Path]::GetTempPath()) "$pipelineName-$([guid]::NewGuid().ToString('N')).json"
    try {
        [System.IO.File]::WriteAllText(
            $requestPath,
            $requestBody,
            [System.Text.UTF8Encoding]::new($false)
        )
        & az rest `
            --method put `
            --url $pipelineUrl `
            --body "@$requestPath" `
            --only-show-errors `
            --output none
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to update ADF pipeline $pipelineName."
        }
    }
    finally {
        Remove-Item -Path $requestPath -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Uploaded schema mappings to $ConfigContainerName/schemas."
Write-Host "Configured GitHub Copilot routing in $pipelineName."