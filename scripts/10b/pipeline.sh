#!/usr/bin/env bash
# Re-run the full 10B model registry pipeline end-to-end.
#
# Output target — first match wins:
#   1. $BWM_10B_ROOT (a checkout of difflabai/10B-model)
#   2. $BWM_LOCAL_ROOT (the bwm-server local registry root)
#   3. this repo's own checkout (the directory holding ./global/10B/)
#
# All scripts are idempotent: re-running produces identical output for
# identical input.

set -euo pipefail

cd "$(dirname "$0")/../.."
ROOT="$(pwd)"

step() {
    printf '\n==> %s\n' "$1"
}

step "1/6  Generate per-country, per-category model metadata + run stubs"
python3 scripts/10b/generate.py

step "2/6  Closed-form scorer: compute per-cell run outputs + country rollups"
python3 scripts/10b/scorer.py

step "3/6  Top-up models: dynamics, supervised-trajectory, personal-agent"
python3 scripts/10b/extra_models.py

step "4/6  Unsupervised macro-dynamics (k-means)"
python3 scripts/10b/dynamics.py 6

step "5/6  Per-country agent-context (connect / contribute / advocate)"
python3 scripts/10b/agent_context.py

step "6/6  Regional rollups (UN geoscheme regions)"
python3 scripts/10b/regions.py

step "Forecasts"
python3 scripts/10b/forecasts.py

step "Manifest"
python3 scripts/10b/manifest.py

step "Validation"
python3 scripts/10b/validate.py

# Resolve the actual target the scripts wrote to so the final log line is honest.
TARGET="$(python3 -c 'import sys; sys.path.insert(0, "scripts/10b"); from _paths import tenb_root; print(tenb_root())')"
printf '\nPipeline complete. 10B registry: %s\n' "$TARGET"
