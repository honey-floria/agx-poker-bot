#!/bin/bash
#SBATCH --job-name=noregrets-ng4-project
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=/userhome/cs5/u3680889/noregrets-ng4-project-%j.out
#SBATCH --error=/userhome/cs5/u3680889/noregrets-ng4-project-%j.err

set -euo pipefail

PROJECT="${NOREGRETS_EVAL_ROOT:-/userhome/cs5/u3680889/noregrets-smoke-tools/repo}"
SOURCE="${NOREGRETS_SOURCE:-/userhome/cs5/u3680889/third_party/noregrets}"
FORMAL_ROOT="${NOREGRETS_FORMAL_OUTPUT:-/userhome/cs5/u3680889/poker-distill/data/noregrets-blueprints/formal-v1}"
OUTPUT="${NOREGRETS_NG4_PROJECT_OUTPUT:-/userhome/cs5/u3680889/poker-distill/data/noregrets-blueprints/evaluations/ng4-project-v1}"
CONFIG="${PROJECT}/poker-distill/teachers/noregrets/config/ng4-project-eval-v1.json"
NODE="${NOREGRETS_NODE:-/userhome/cs5/u3680889/agx-poker-bot/.nodeenv/bin/node}"

python3 "${PROJECT}/tools/noregrets/run_ng4_project_evaluation.py" \
  --project "${PROJECT}" \
  --source "${SOURCE}" \
  --config "${CONFIG}" \
  --formal-root "${FORMAL_ROOT}" \
  --output "${OUTPUT}" \
  --node "${NODE}"
