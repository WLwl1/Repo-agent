param(
    [switch]$FullReleasePack
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$reportDir = Join-Path $repoRoot "reports\showcase"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Output ""
    Write-Output "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
        throw "Step '$Name' failed with exit code $LASTEXITCODE"
    }
    if (-not $?) {
        throw "Step '$Name' failed"
    }
}

Invoke-Step "Compile sources" {
    python -m compileall repo_agent tests examples
}

Invoke-Step "Check Web Studio JavaScript" {
    node --check web/app.js
}

Invoke-Step "Run portable benchmark adapter" {
    python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/showcase/benchmark-adapter.json --json | Out-Null
    python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/showcase/benchmark-adapter.md | Out-Null
}

Invoke-Step "Diagnose and repair benchmark evidence" {
    python -m repo_agent benchmark-diagnose --benchmark reports/showcase/benchmark-adapter.json --output reports/showcase/benchmark-diagnostics.md | Out-Null
    python -m repo_agent benchmark-repair-card --benchmark reports/showcase/benchmark-adapter.json --output reports/showcase/benchmark-repair-card.md | Out-Null
}

Invoke-Step "Synthesize, verify, compile, and workbench repair rules" {
    python -m repo_agent benchmark-repair-synthesize --benchmark reports/showcase/benchmark-adapter.json --output reports/showcase/benchmark-repair-synthesis.json --json | Out-Null
    python -m repo_agent benchmark-repair-synthesize --benchmark reports/showcase/benchmark-adapter.json --output reports/showcase/benchmark-repair-synthesis.md | Out-Null
    python -m repo_agent benchmark-repair-verify-implementation --synthesis reports/showcase/benchmark-repair-synthesis.json --output reports/showcase/benchmark-repair-implementation.json --json | Out-Null
    python -m repo_agent benchmark-repair-verify-implementation --synthesis reports/showcase/benchmark-repair-synthesis.json --output reports/showcase/benchmark-repair-implementation.md | Out-Null
    python -m repo_agent benchmark-repair-compile --synthesis reports/showcase/benchmark-repair-synthesis.json --implementation reports/showcase/benchmark-repair-implementation.json --output reports/showcase/benchmark-repair-compiler.json --json | Out-Null
    python -m repo_agent benchmark-repair-compile --synthesis reports/showcase/benchmark-repair-synthesis.json --implementation reports/showcase/benchmark-repair-implementation.json --output reports/showcase/benchmark-repair-compiler.md | Out-Null
    python -m repo_agent benchmark-repair-workbench --compiler reports/showcase/benchmark-repair-compiler.json --output reports/showcase/benchmark-repair-workbench.md | Out-Null
}

if ($FullReleasePack) {
    Invoke-Step "Build full release pack" {
        python -m repo_agent release-pack --output-dir reports/release-pack
        python -m repo_agent verify-release-pack --manifest reports/release-pack/manifest.json
    }
}

Invoke-Step "Print showcase metrics" {
    $summaryCode = @'
import json
from pathlib import Path

root = Path("reports/showcase")
b = json.load(open(root / "benchmark-adapter.json", encoding="utf-8"))
s = json.load(open(root / "benchmark-repair-synthesis.json", encoding="utf-8"))
i = json.load(open(root / "benchmark-repair-implementation.json", encoding="utf-8"))
c = json.load(open(root / "benchmark-repair-compiler.json", encoding="utf-8"))

print("Top-1:", "{:.2%}".format(b["metrics"]["top1_accuracy"]))
print("Top-3:", "{:.2%}".format(b["metrics"]["top3_accuracy"]))
print("Repair rules:", s["summary"]["validated_rule_count"], "validated /", s["summary"]["proposed_rule_count"], "proposed")
print("Implementation:", i["summary"]["implemented_validated_rule_count"], "/", i["summary"]["validated_rule_count"], "validated rules implemented")
print("Compiler:", c["status"], "with", c["summary"]["ablation_toggle_count"], "ablation toggles")
manifest = Path("reports/release-pack/manifest.json")
if manifest.is_file():
    m = json.load(open(manifest, encoding="utf-8"))
    metrics = m.get("metrics", {})
    if metrics.get("artifact_provenance_status"):
        print(
            "Provenance:",
            metrics.get("artifact_provenance_status", "unknown"),
            "with",
            metrics.get("artifact_provenance_complete_claims", 0),
            "/",
            metrics.get("artifact_provenance_claims", 0),
            "complete claims and",
            metrics.get("artifact_provenance_edges", 0),
            "edges",
        )
'@
    $summaryCode | python -
}

Write-Output ""
Write-Output "Showcase reports written under reports\showcase."
Write-Output "Start with reports\showcase\benchmark-repair-workbench.md for the repair-to-ablation story."
Write-Output "Use -FullReleasePack to also inspect reports\release-pack\artifact-provenance.md."
