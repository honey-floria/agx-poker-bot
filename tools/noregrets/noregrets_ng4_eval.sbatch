#!/bin/bash
#SBATCH --job-name=noregrets-ng4a
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:2
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=/userhome/cs5/u3680889/noregrets-ng4a-%j.out
#SBATCH --error=/userhome/cs5/u3680889/noregrets-ng4a-%j.err

set -euo pipefail

source "$HOME/.cargo/env"

SOURCE_DIR="${NOREGRETS_SOURCE:-/userhome/cs5/u3680889/third_party/noregrets}"
STAGING_ROOT="${NOREGRETS_EVAL_ROOT:-/userhome/cs5/u3680889/noregrets-smoke-tools/repo}"
FORMAL_ROOT="${NOREGRETS_FORMAL_OUTPUT:-/userhome/cs5/u3680889/poker-distill/data/noregrets-blueprints/formal-v1}"
OUTPUT_DIR="${NOREGRETS_NG4_OUTPUT:-/userhome/cs5/u3680889/poker-distill/data/noregrets-blueprints/evaluations/ng4-v1}"
TOOLS_DIR="${STAGING_ROOT}/tools/noregrets"
CONFIG="${STAGING_ROOT}/poker-distill/teachers/noregrets/config/ng4-eval-v1.json"

python3 "${TOOLS_DIR}/check_environment.py" require --source "${SOURCE_DIR}"
python3 "${TOOLS_DIR}/run_ng4_evaluation.py" \
  --source "${SOURCE_DIR}" \
  --config "${CONFIG}" \
  --formal-root "${FORMAL_ROOT}" \
  --output "${OUTPUT_DIR}"
