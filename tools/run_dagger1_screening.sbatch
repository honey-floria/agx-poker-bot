#!/bin/bash
#SBATCH --job-name=dagger1-screen
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=/userhome/cs5/u3680889/dagger1-screen-%j.out
#SBATCH --error=/userhome/cs5/u3680889/dagger1-screen-%j.err

set -euo pipefail

PROJECT="${AGX_PROJECT_ROOT:-/userhome/cs5/u3680889/agx-poker-bot}"
NODE="${AGX_NODE:-${PROJECT}/.nodeenv/bin/node}"
PYTHON="${AGX_PYTHON:-${PROJECT}/.venv/bin/python}"
CONFIG="${PROJECT}/poker-distill/experiments/behavior_dagger1_screening.json"
OUTPUT="${AGX_DAGGER1_SCREEN_OUTPUT:-${PROJECT}/poker-distill/data/dagger/round_1/screening-v1}"

cd "${PROJECT}"

"${PYTHON}" tools/run_dagger1_screening.py \
  --project "${PROJECT}" \
  --config "${CONFIG}" \
  --output "${OUTPUT}" \
  --node "${NODE}"
