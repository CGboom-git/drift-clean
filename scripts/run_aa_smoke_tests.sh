#!/usr/bin/env bash
set -u

REPO_ROOT="${1:-$(pwd)}"
ENV_FILE="${ENV_FILE:-/data/home/qyc/.config/drift/openai.env}"
CONDA_SH="${CONDA_SH:-/usr/local/miniconda3/etc/profile.d/conda.sh}"
MODEL="${MODEL:-gpt-4o-mini-2024-07-18}"
RUNS_DIR="${RUNS_DIR:-$REPO_ROOT/runs}"

run_cmd() {
  local label="$1"
  shift
  echo "==> ${label}"
  "$@"
  local status=$?
  echo "==> ${label} exit=${status}"
  return $status
}

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

if [ -f "$CONDA_SH" ]; then
  # shellcheck disable=SC1090
  source "$CONDA_SH"
  conda activate drift
fi

cd "$REPO_ROOT"

mkdir -p "$RUNS_DIR"

run_cmd "raw_clean" python pipeline_main.py --model "$MODEL" --suites banking --target_user_tasks 0 --force_rerun
run_cmd "drift_clean" python pipeline_main.py --model "$MODEL" --suites banking --target_user_tasks 0 --build_constraints --injection_isolation --dynamic_validation --force_rerun
run_cmd "aa_clean" python pipeline_main.py --model "$MODEL" --suites banking --target_user_tasks 0 --build_constraints --injection_isolation --dynamic_validation --enable_argument_authority_drift --aa_global_contract_path contracts/agentdojo_ifc_global_tool_contract_semantic_review_gpt55.json --aa_debug --force_rerun
run_cmd "drift_attack" python pipeline_main.py --model "$MODEL" --suites banking --target_user_tasks 0 --do_attack --attack_type important_instructions --target_injection_tasks injection_task_0 --build_constraints --injection_isolation --dynamic_validation --force_rerun
run_cmd "aa_attack" python pipeline_main.py --model "$MODEL" --suites banking --target_user_tasks 0 --do_attack --attack_type important_instructions --target_injection_tasks injection_task_0 --build_constraints --injection_isolation --dynamic_validation --enable_argument_authority_drift --aa_global_contract_path contracts/agentdojo_ifc_global_tool_contract_semantic_review_gpt55.json --aa_debug --force_rerun
run_cmd "aa_subset" python pipeline_main.py --model "$MODEL" --suites banking --target_user_tasks 0,1,2 --do_attack --attack_type important_instructions --target_injection_tasks injection_task_0,injection_task_1 --build_constraints --injection_isolation --dynamic_validation --enable_argument_authority_drift --aa_global_contract_path contracts/agentdojo_ifc_global_tool_contract_semantic_review_gpt55.json --aa_debug --force_rerun

python scripts/summarize_aa_smoke.py "$RUNS_DIR/$MODEL"
