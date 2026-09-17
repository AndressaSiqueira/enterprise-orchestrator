param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Organization,
    [string]$OutputRoot = (Join-Path $PSScriptRoot "data"),
    [ValidateRange(1, 365)]
    [int]$Days = 28,
    [datetime]$EndDate = [datetime]::UtcNow.Date.AddDays(-3)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$apiVersion = "2026-03-10"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$runTimestamp = [datetime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$runDirectory = Join-Path $OutputRoot $runTimestamp
$rawDirectory = Join-Path $runDirectory "raw"
$metricsDirectory = Join-Path $rawDirectory "metrics"

New-Item -ItemType Directory -Path $metricsDirectory -Force | Out-Null

function Write-JsonFile {
    param(
        [Parameter(Mandatory)]
        [string]$Path,
        [Parameter(Mandatory)]
        [AllowNull()]
        $Value
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $json = $Value | ConvertTo-Json -Depth 100
    [System.IO.File]::WriteAllText($Path, $json, $utf8NoBom)
}

function Invoke-GitHubApi {
    param(
        [Parameter(Mandatory)]
        [string]$Endpoint,
        [switch]$Paginate
    )

    $arguments = @(
        "api",
        "--method", "GET",
        $Endpoint,
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: $apiVersion"
    )

    if ($Paginate) {
        $arguments += @("--paginate", "--slurp")
    }

    $output = & gh @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw (($output | Out-String).Trim())
    }

    $text = (($output | Out-String).Trim())
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }

    return $text | ConvertFrom-Json
}

function Add-ManifestEntry {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[object]]$Entries,
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string]$Status,
        [string]$Path,
        [string]$Message
    )

    $Entries.Add([pscustomobject]@{
        name = $Name
        status = $Status
        path = $Path
        message = $Message
    })
}

function Save-ApiResource {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[object]]$Entries,
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string]$Endpoint,
        [Parameter(Mandatory)]
        [string]$RelativePath,
        [switch]$Paginate
    )

    try {
        $value = Invoke-GitHubApi -Endpoint $Endpoint -Paginate:$Paginate
        $fullPath = Join-Path $runDirectory $RelativePath
        Write-JsonFile -Path $fullPath -Value $value
        Add-ManifestEntry -Entries $Entries -Name $Name -Status "ok" -Path $RelativePath
        return $value
    }
    catch {
        Add-ManifestEntry -Entries $Entries -Name $Name -Status "error" -Message $_.Exception.Message
        return $null
    }
}

function Save-MetricsReport {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[object]]$Entries,
        [Parameter(Mandatory)]
        [string]$ReportType,
        [Parameter(Mandatory)]
        [string]$Endpoint,
        [Parameter(Mandatory)]
        [string]$DateLabel
    )

    $entryName = "metrics-$ReportType-$DateLabel"
    try {
        $report = Invoke-GitHubApi -Endpoint $Endpoint
        if ($null -eq $report) {
            Add-ManifestEntry -Entries $Entries -Name $entryName -Status "no-content"
            return
        }

        $reportDirectory = Join-Path $metricsDirectory $ReportType
        New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
        $metadataPath = Join-Path $reportDirectory "$DateLabel.metadata.json"
        Write-JsonFile -Path $metadataPath -Value $report

        $part = 0
        foreach ($downloadLink in $report.download_links) {
            $part++
            $destination = Join-Path $reportDirectory "$DateLabel.part-$part.ndjson"
            Invoke-WebRequest -Uri $downloadLink -OutFile $destination -UseBasicParsing
        }

        $relativePath = "raw/metrics/$ReportType/$DateLabel"
        Add-ManifestEntry -Entries $Entries -Name $entryName -Status "ok" -Path $relativePath -Message "$part file(s)"
    }
    catch {
        Add-ManifestEntry -Entries $Entries -Name $entryName -Status "error" -Message $_.Exception.Message
    }
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) is required."
}

& gh auth status 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI is not authenticated."
}

$entries = [System.Collections.Generic.List[object]]::new()
$year = [datetime]::UtcNow.Year
$month = [datetime]::UtcNow.Month

Save-ApiResource -Entries $entries -Name "copilot-billing" `
    -Endpoint "/orgs/$Organization/copilot/billing" `
    -RelativePath "raw/copilot-billing.json" | Out-Null

Save-ApiResource -Entries $entries -Name "copilot-seats" `
    -Endpoint "/orgs/$Organization/copilot/billing/seats?per_page=100" `
    -RelativePath "raw/copilot-seats.pages.json" -Paginate | Out-Null

Save-ApiResource -Entries $entries -Name "billing-ai-credit" `
    -Endpoint "/organizations/$Organization/settings/billing/ai_credit/usage?year=$year&month=$month" `
    -RelativePath "raw/billing-ai-credit-$year-$('{0:D2}' -f $month).json" | Out-Null

Save-ApiResource -Entries $entries -Name "billing-premium-request" `
    -Endpoint "/organizations/$Organization/settings/billing/premium_request/usage?year=$year&month=$month" `
    -RelativePath "raw/billing-premium-request-$year-$('{0:D2}' -f $month).json" | Out-Null

Save-ApiResource -Entries $entries -Name "billing-usage" `
    -Endpoint "/organizations/$Organization/settings/billing/usage?year=$year&month=$month" `
    -RelativePath "raw/billing-usage-$year-$('{0:D2}' -f $month).json" | Out-Null

Save-ApiResource -Entries $entries -Name "billing-summary" `
    -Endpoint "/organizations/$Organization/settings/billing/usage/summary?year=$year&month=$month" `
    -RelativePath "raw/billing-summary-$year-$('{0:D2}' -f $month).json" | Out-Null

Save-ApiResource -Entries $entries -Name "budgets" `
    -Endpoint "/organizations/$Organization/settings/billing/budgets?per_page=100" `
    -RelativePath "raw/budgets.pages.json" -Paginate | Out-Null

Save-MetricsReport -Entries $entries -ReportType "organization-28-day" `
    -Endpoint "/orgs/$Organization/copilot/metrics/reports/organization-28-day/latest" `
    -DateLabel "latest"

Save-MetricsReport -Entries $entries -ReportType "users-28-day" `
    -Endpoint "/orgs/$Organization/copilot/metrics/reports/users-28-day/latest" `
    -DateLabel "latest"

for ($offset = $Days - 1; $offset -ge 0; $offset--) {
    $day = $EndDate.AddDays(-$offset).ToString("yyyy-MM-dd")
    $reports = @(
        "organization-1-day",
        "users-1-day",
        "user-teams-1-day",
        "repos-1-day"
    )

    foreach ($reportType in $reports) {
        Save-MetricsReport -Entries $entries -ReportType $reportType `
            -Endpoint "/orgs/$Organization/copilot/metrics/reports/$reportType`?day=$day" `
            -DateLabel $day
    }
}

$manifest = [pscustomobject]@{
    schema_version = 1
    organization = $Organization
    api_version = $apiVersion
    collected_at_utc = [datetime]::UtcNow.ToString("o")
    requested_window = [pscustomobject]@{
        start_day = $EndDate.AddDays(-($Days - 1)).ToString("yyyy-MM-dd")
        end_day = $EndDate.ToString("yyyy-MM-dd")
        days = $Days
    }
    entries = $entries
}

Write-JsonFile -Path (Join-Path $runDirectory "manifest.json") -Value $manifest

$okCount = @($entries | Where-Object status -eq "ok").Count
$noContentCount = @($entries | Where-Object status -eq "no-content").Count
$errorCount = @($entries | Where-Object status -eq "error").Count

Write-Host "Collection directory: $runDirectory"
Write-Host "OK: $okCount | No content: $noContentCount | Errors: $errorCount"

if ($errorCount -gt 0) {
    exit 2
}