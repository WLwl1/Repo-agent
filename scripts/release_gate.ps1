$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$reportDir = Join-Path $repoRoot "reports"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$tempRoot = Join-Path $repoRoot ".tmp"
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
$tempDir = Join-Path $tempRoot ("release-gate-temp-" + [System.Diagnostics.Process]::GetCurrentProcess().Id)
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
$pytestTempDir = Join-Path $tempDir "pytest"
New-Item -ItemType Directory -Force -Path $pytestTempDir | Out-Null
$env:TMP = $tempDir
$env:TEMP = $tempDir
$env:PYTEST_DEBUG_TEMPROOT = $tempDir

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

Invoke-Step "Compile Python sources" {
    python -m compileall repo_agent tests examples
}

Invoke-Step "Check web JavaScript syntax" {
    node --check web/app.js
}

Invoke-Step "Run pytest suite" {
    python -m pytest --basetemp $pytestTempDir
}

Invoke-Step "Run retrieval ablation" {
    python -m repo_agent ablate --output reports/ablation-report.md
}

Invoke-Step "Run counterfactual hard-negative benchmark" {
    python -m repo_agent counterfactual --output reports/counterfactual-report.md
}

Invoke-Step "Run portable benchmark adapter" {
    python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.json
    python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.md
}

Invoke-Step "Diagnose portable benchmark generalization" {
    python -m repo_agent benchmark-diagnose --benchmark reports/benchmark-adapter.json --output reports/benchmark-diagnostics.md
}

Invoke-Step "Validate portable benchmark repair card" {
    python -m repo_agent benchmark-repair-card --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-card.md
}

Invoke-Step "Synthesize portable benchmark repair rules" {
    python -m repo_agent benchmark-repair-synthesize --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-synthesis.md
}

Invoke-Step "Verify portable benchmark repair implementation" {
    python -m repo_agent benchmark-repair-synthesize --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-synthesis.json
    python -m repo_agent benchmark-repair-verify-implementation --synthesis reports/benchmark-repair-synthesis.json --output reports/benchmark-repair-implementation.json
    python -m repo_agent benchmark-repair-verify-implementation --synthesis reports/benchmark-repair-synthesis.json --output reports/benchmark-repair-implementation.md
}

Invoke-Step "Compile portable benchmark repair interventions" {
    python -m repo_agent benchmark-repair-compile --synthesis reports/benchmark-repair-synthesis.json --implementation reports/benchmark-repair-implementation.json --output reports/benchmark-repair-compiler.md
    python -m repo_agent benchmark-repair-compile --synthesis reports/benchmark-repair-synthesis.json --implementation reports/benchmark-repair-implementation.json --output reports/benchmark-repair-compiler.json
}

Invoke-Step "Build portable benchmark repair workbench" {
    python -m repo_agent benchmark-repair-workbench --compiler reports/benchmark-repair-compiler.json --output reports/benchmark-repair-workbench.md
}

Invoke-Step "Run adversarial proof attack benchmark" {
    python -m repo_agent proof-attack --output-dir reports/proof-attack-benchmark --output reports/proof-attack-benchmark.json
}

Invoke-Step "Generate adversarial proof attack report" {
    python -m repo_agent proof-attack --output-dir reports/proof-attack-benchmark --output reports/proof-attack-benchmark.md
}

Invoke-Step "Generate adversarial proof attack leaderboard" {
    python -m repo_agent proof-attack-leaderboard --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-leaderboard.md
}

Invoke-Step "Generate adversarial proof attack triage" {
    python -m repo_agent proof-attack-triage --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-triage.md
}

Invoke-Step "Synthesize adversarial proof attack defense policy JSON" {
    python -m repo_agent proof-attack-policy --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-policy.json
}

Invoke-Step "Generate adversarial proof attack defense policy report" {
    python -m repo_agent proof-attack-policy --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-policy.md
}

Invoke-Step "Run adaptive proof attack policy curriculum JSON" {
    python -m repo_agent proof-attack-adaptive --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --output-dir reports/proof-attack-adaptive --output reports/proof-attack-adaptive.json
}

Invoke-Step "Generate adaptive proof attack policy curriculum report" {
    python -m repo_agent proof-attack-adaptive --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --output-dir reports/proof-attack-adaptive --output reports/proof-attack-adaptive.md
}

Invoke-Step "Synthesize adaptive proof attack policy repair JSON" {
    python -m repo_agent proof-attack-repair --policy reports/proof-attack-policy.json --adaptive reports/proof-attack-adaptive.json --output reports/proof-attack-repair.json
}

Invoke-Step "Generate adaptive proof attack policy repair report" {
    python -m repo_agent proof-attack-repair --policy reports/proof-attack-policy.json --adaptive reports/proof-attack-adaptive.json --output reports/proof-attack-repair.md
}

Invoke-Step "Generate proof attack minimax certificate JSON" {
    python -m repo_agent proof-attack-certificate --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --adaptive reports/proof-attack-adaptive.json --repair reports/proof-attack-repair.json --output reports/proof-attack-certificate.json
}

Invoke-Step "Generate proof attack minimax certificate report" {
    python -m repo_agent proof-attack-certificate --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --adaptive reports/proof-attack-adaptive.json --repair reports/proof-attack-repair.json --output reports/proof-attack-certificate.md
}

Invoke-Step "Generate adversarial proof attack scorecard JSON" {
    python -m repo_agent proof-attack-scorecard --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-scorecard.json --sarif-output reports/proof-attack-scorecard.sarif --github-annotations --fail-on-fail
}

Invoke-Step "Generate adversarial proof attack scorecard report" {
    python -m repo_agent proof-attack-scorecard --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-scorecard.md
}

Invoke-Step "Run adversarial proof attack CEGAR loop" {
    python -m repo_agent proof-attack-cegar --output-dir reports/proof-attack-cegar --output reports/proof-attack-cegar.md
}

$question = "Which function finally writes streamed tokens for the public /api/chat endpoint?"

Invoke-Step "Generate proof-carrying report" {
    python -m repo_agent report --repo .\examples\counterfactual_agent_app --question $question --output reports/proof-carrying-counterfactual.html
}

Invoke-Step "Generate proof evidence bundle" {
    python -m repo_agent bundle --repo .\examples\counterfactual_agent_app --question $question --format json --output reports/proof-carrying-counterfactual.bundle.json
}

Invoke-Step "Replay proof strictly" {
    python -m repo_agent replay-proof --bundle reports/proof-carrying-counterfactual.bundle.json --strict --output reports/proof-replay-report.md
}

Invoke-Step "Run proof mutation lab" {
    python -m repo_agent proof-mutate --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-mutation-report.md
}

Invoke-Step "Generate proof reliability scorecard" {
    python -m repo_agent proof-scorecard --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-scorecard.md
}

Invoke-Step "Generate proof-guided impact analysis" {
    python -m repo_agent impact --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-impact-report.md
}

Invoke-Step "Generate proof regression contract" {
    python -m repo_agent contract --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-regression-contract.json
}

Invoke-Step "Verify proof regression contract" {
    python -m repo_agent verify-contract --contract reports/proof-regression-contract.json --output reports/proof-regression-contract-verification.md
}

Invoke-Step "Run proof-backed PR guard" {
    python -m repo_agent pr-guard --contract reports/proof-regression-contract.json --changed-files server.js --fail-on never --output reports/proof-pr-guard-report.md --sarif-output reports/proof-pr-guard.sarif
}

Invoke-Step "Generate release pack" {
    python -m repo_agent release-pack --output-dir reports/release-pack
}

Invoke-Step "Generate agent reliability frontier" {
    python -m repo_agent agent-frontier --manifest reports/release-pack/manifest.json --output reports/agent-frontier.md
}

Invoke-Step "Run agent frontier causal ablation" {
    python -m repo_agent agent-frontier-ablate --manifest reports/release-pack/manifest.json --output reports/agent-frontier-ablation.md
}

Invoke-Step "Map agent evidence interactions" {
    python -m repo_agent agent-frontier-interactions --manifest reports/release-pack/manifest.json --output reports/agent-frontier-interactions.md
}

Invoke-Step "Bootstrap agent frontier stability" {
    python -m repo_agent agent-frontier-stability --manifest reports/release-pack/manifest.json --output reports/agent-frontier-stability.md
}

Invoke-Step "Generate agent artifact evaluation card" {
    python -m repo_agent agent-artifact-review --manifest reports/release-pack/manifest.json --output reports/agent-artifact-review.md
}

Invoke-Step "Generate artifact provenance graph" {
    python -m repo_agent artifact-provenance --manifest reports/release-pack/manifest.json --output reports/artifact-provenance.md
}

Invoke-Step "Run temporal proof regression" {
    python -m repo_agent temporal-proof-regression --contract reports/release-pack/proof-regression-contract.json --git-repo reports/release-pack/_temporal-proof-demo-repo --rev-range HEAD --output reports/temporal-proof-regression.md
}

Invoke-Step "Run temporal repair benchmark" {
    python -m repo_agent temporal-repair-benchmark --output-dir reports/temporal-repair-benchmark --output reports/temporal-repair-benchmark.json
}

Invoke-Step "Generate temporal repair scorecard JSON" {
    python -m repo_agent temporal-repair-scorecard --benchmark reports/temporal-repair-benchmark.json --output reports/temporal-repair-scorecard.json --sarif-output reports/temporal-repair-scorecard.sarif --github-annotations --fail-on-fail
}

Invoke-Step "Generate temporal repair scorecard report" {
    python -m repo_agent temporal-repair-scorecard --benchmark reports/temporal-repair-benchmark.json --output reports/temporal-repair-scorecard.md
}

Invoke-Step "Run multi-agent evidence court" {
    python -m repo_agent agent-court --bundle reports/proof-carrying-counterfactual.bundle.json --attack-scorecard reports/proof-attack-scorecard.json --temporal-scorecard reports/temporal-repair-scorecard.json --output reports/agent-court.md
}

Invoke-Step "Verify release pack integrity" {
    python -m repo_agent verify-release-pack --manifest reports/release-pack/manifest.json
}

Invoke-Step "Scan tracked files for obvious secrets" {
    & "$PSScriptRoot\prepublish_check.ps1"
}

Write-Output ""
Write-Output "Release gate passed. Reports written under reports/."
