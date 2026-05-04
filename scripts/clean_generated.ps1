$ErrorActionPreference = "Stop"

$paths = @(
    ".cache",
    ".pytest_tmp",
    ".tmp",
    "logs",
    "reports",
    "runs",
    "test-tmp",
    "repo_agent\\__pycache__"
)

foreach ($relativePath in $paths) {
    $target = Join-Path $PSScriptRoot "..\\$relativePath"
    $resolved = [System.IO.Path]::GetFullPath($target)
    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
        Write-Host "Removed $resolved"
    }
}
