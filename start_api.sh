#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/leron/PipelineWorkSpace/Multi_AgentDecisionCouncil"
CONDA_SH="/Users/leron/miniconda3/etc/profile.d/conda.sh"

cd "$PROJECT_DIR"
source "$CONDA_SH"
conda activate base311

exec python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
