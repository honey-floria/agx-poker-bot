#!/bin/bash
#SBATCH --job-name=noregrets-formal-v1
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:2
#SBATCH --mem=64G
#SBATCH --time=20:00:00
#SBATCH --output=/userhome/cs5/u3680889/noregrets-formal-%j.out
#SBATCH --error=/userhome/cs5/u3680889/noregrets-formal-%j.err

set -euo pipefail

source "$HOME/.cargo/env"

SOURCE_DIR="${NOREGRETS_SOURCE:-/userhome/cs5/u3680889/third_party/noregrets}"
STAGING_ROOT="${NOREGRETS_TRAINING_ROOT:-/userhome/cs5/u3680889/noregrets-smoke-tools/repo}"
OUTPUT_DIR="${NOREGRETS_FORMAL_OUTPUT:-/userhome/cs5/u3680889/poker-distill/data/noregrets-blueprints/formal-v1}"
TOOLS_DIR="${STAGING_ROOT}/tools/noregrets"
CONFIG="${STAGING_ROOT}/poker-distill/teachers/noregrets/config/blueprint-formal-v1.json"

python3 "${TOOLS_DIR}/check_environment.py" require --source "${SOURCE_DIR}"
python3 "${TOOLS_DIR}/run_formal_training.py" \
  --source "${SOURCE_DIR}" \
  --config "${CONFIG}" \
  --output "${OUTPUT_DIR}"
