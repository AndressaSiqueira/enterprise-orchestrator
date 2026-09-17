param(
    [Parameter(Mandatory)]
    [string]$Database,

    [Parameter(Mandatory)]
    [string]$Path,

    [Parameter(Mandatory)]
    [ValidatePattern("^https://.+\.kusto\.windows\.net/?$")]
    [string]$ClusterUri
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI (az) is required."
}

$resolvedPath = (Resolve-Path $Path).Path
$content = Get-Content -LiteralPath $resolvedPath -Raw
$content = [regex]::Replace($content, '(?m)^\s*//.*(?:\r?\n|$)', '')
$commands = @(
    [regex]::Split($content, '(?m)(?=^\.)') |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_.StartsWith('.') }
)
if ($commands.Count -eq 0) {
    throw "No Kusto management commands were found in $resolvedPath."
}

$token = & az account get-access-token `
    --resource "https://kusto.kusto.windows.net" `
    --query accessToken `
    --output tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) {
    throw "Unable to acquire a Kusto access token."
}

try {
    $headers = @{ Authorization = "Bearer $token" }
    $commandNumber = 0
    foreach ($command in $commands) {
        $commandNumber++
        $body = @{ db = $Database; csl = $command } | ConvertTo-Json -Compress
        $null = Invoke-RestMethod `
            -Method Post `
            -Uri "$($ClusterUri.TrimEnd('/'))/v1/rest/mgmt" `
            -Headers $headers `
            -ContentType "application/json" `
            -Body $body
        Write-Host "Applied command $commandNumber of $($commands.Count)."
    }
}
finally {
    Remove-Variable token -ErrorAction SilentlyContinue
}