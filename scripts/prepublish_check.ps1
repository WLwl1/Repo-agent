$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Disable Git's C-style path quoting so PowerShell can validate tracked files
# whose names contain non-ASCII characters (for example, Chinese documents).
$tracked = git -c core.quotePath=false ls-files
$candidates = @($tracked)
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
            if ($relativePath -eq ".env.example" -and $match.Line.Trim() -match "=\s*$") {
                continue
            }
            $findings.Add("${relativePath}:$($match.LineNumber): potential secret-like value")
        }
    }
}

if ($findings.Count -gt 0) {
    Write-Output "Potential secrets found:"
    $findings | Sort-Object -Unique | ForEach-Object { Write-Output $_ }
    exit 1
}

Write-Output "No obvious secrets found in tracked files."
