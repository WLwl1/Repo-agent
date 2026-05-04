$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$tracked = git ls-files
$candidates = @($tracked) + @(".env")
$patterns = @(
    "sk-[A-Za-z0-9_-]{20,}",
    "ghp_[A-Za-z0-9]{20,}",
    "github_pat_[A-Za-z0-9_]{20,}",
    "^(OPENAI_API_KEY|API_KEY|SECRET_KEY|TOKEN|PASSWORD)\s*=\s*\S+"
)

$findings = New-Object System.Collections.Generic.List[string]

foreach ($relativePath in ($candidates | Sort-Object -Unique)) {
    if (-not $relativePath) {
        continue
    }
    $fullPath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path $fullPath -PathType Leaf)) {
        continue
    }

    foreach ($pattern in $patterns) {
        $matches = Select-String -Path $fullPath -Pattern $pattern -AllMatches -CaseSensitive -ErrorAction SilentlyContinue
        foreach ($match in $matches) {
            $line = $match.Line.Trim()
            if ($relativePath -eq ".env.example" -and $line -match "=\s*$") {
                continue
            }
            $findings.Add("${relativePath}:$($match.LineNumber): $line")
        }
    }
}

if ($findings.Count -gt 0) {
    Write-Output "Potential secrets found:"
    $findings | Sort-Object -Unique | ForEach-Object { Write-Output $_ }
    exit 1
}

Write-Output "No obvious secrets found in tracked files."
