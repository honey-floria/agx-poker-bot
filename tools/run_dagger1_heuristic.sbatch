#!/bin/bash
#SBATCH --job-name=dagger1-heuristic
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=/userhome/cs5/u3680889/dagger1-heuristic-%j.out
#SBATCH --error=/userhome/cs5/u3680889/dagger1-heuristic-%j.err

set -euo pipefail

PROJECT="${AGX_PROJECT:-/userhome/cs5/u3680889/agx-poker-bot}"
PYTHON="${AGX_PYTHON:-${PROJECT}/.venv/bin/python}"
NODE="${AGX_NODE:-${PROJECT}/.nodeenv/bin/node}"
ROUND="${PROJECT}/poker-distill/data/dagger/round_1"
BASE="${PROJECT}/poker-distill/data/parsed-decisions/top20"
DATASET="${ROUND}/dataset-heuristic"
LABELS="${ROUND}/policy_labels.jsonl"
LABEL_REPORT="${PROJECT}/poker-distill/reports/policy_labels_round1.json"
DATASET_REPORT="${PROJECT}/poker-distill/reports/dagger1_dataset_manifest.json"

for file in "${PYTHON}" "${NODE}" "${ROUND}/mined_top10000.jsonl" \
  "${BASE}/train.jsonl" "${BASE}/validation.jsonl" "${BASE}/test.jsonl"; do
  test -e "${file}" || { echo "missing required file: ${file}" >&2; exit 1; }
done

cd "${PROJECT}"

"${NODE}" tools/label_policy_states.js \
  --input "${ROUND}/mined_top10000.jsonl" \
  --policy submission.js \
  --output "${LABELS}" \
  --report "${LABEL_REPORT}" \
  --teacher-version submission-stateless-v1

"${PYTHON}" tools/build_dagger_dataset.py \
  --base-dir "${BASE}" \
  --labels "${LABELS}" \
  --output-dir "${DATASET}" \
  --report "${DATASET_REPORT}" \
  --data-version public-replay-top20-dagger1-heuristic-v1

for seed in 7607 17607 27607; do
  output="${PROJECT}/neural/artifacts/behavior-dagger1-heuristic-seed-${seed}"
  "${PYTHON}" neural/train_behavior_clone_v2.py \
    --data-dir "${DATASET}" \
    --data-version public-replay-top20-dagger1-heuristic-v1 \
    --output-dir "${output}" \
    --epochs 60 \
    --batch-size 2048 \
    --patience 8 \
    --class-weighting none \
    --seed "${seed}" \
    --device cuda
  "${PYTHON}" neural/export_behavior_v2.py \
    --model "${output}/model.json" \
    --output "${output}/submission.js"
  for confidence in 095 099; do
    threshold="0.${confidence#0}"
    "${PYTHON}" neural/export_behavior_hybrid.py \
      --heuristic submission.js \
      --neural "${output}/submission.js" \
      --output "${output}/hybrid-postflop-${confidence}.js" \
      --min-confidence "${threshold}"
    "${PYTHON}" tools/validate.py "${output}/hybrid-postflop-${confidence}.js"
  done
done

echo "DAgger round 1 labeling, dataset build, and three-seed training completed."
