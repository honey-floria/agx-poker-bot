#!/bin/bash
#SBATCH --job-name=noregrets-smoke
#SBATCH --partition=debug
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00

set -euo pipefail

source "$HOME/.cargo/env"

SOURCE_DIR="${NOREGRETS_SOURCE:-/userhome/cs5/u3680889/third_party/noregrets}"
STAGING_ROOT="${NOREGRETS_SMOKE_ROOT:-/userhome/cs5/u3680889/noregrets-smoke-tools/repo}"
TOOLS_DIR="${STAGING_ROOT}/tools/noregrets"
CONFIG="${STAGING_ROOT}/poker-distill/teachers/noregrets/config/blueprint-smoke.json"
OUTPUT_ROOT="${NOREGRETS_SMOKE_OUTPUT:-/userhome/cs5/u3680889/poker-distill/data/noregrets-blueprints/smoke}"
OUTPUT_DIR="${OUTPUT_ROOT}/job-${SLURM_JOB_ID}"

python3 "${TOOLS_DIR}/check_environment.py" require --source "${SOURCE_DIR}"
python3 "${TOOLS_DIR}/run_smoke.py" \
  --source "${SOURCE_DIR}" \
  --config "${CONFIG}" \
  --output "${OUTPUT_DIR}"

echo "NoRegrets smoke artifacts: ${OUTPUT_DIR}"
