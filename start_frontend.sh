#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/leron/PipelineWorkSpace/Multi_AgentDecisionCouncil/frontend"

cd "$PROJECT_DIR"
exec npm run dev -- --host 127.0.0.1 --port 5173
