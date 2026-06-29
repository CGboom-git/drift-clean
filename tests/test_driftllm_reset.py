from types import SimpleNamespace

import pytest

pytest.importorskip("agentdojo")

from DRIFTLLM import DRIFTLLM


def make_llm(enable_argument_authority_drift: bool = True) -> DRIFTLLM:
    args = SimpleNamespace(
        enable_argument_authority_drift=enable_argument_authority_drift,
        aa_global_contract_path=None,
        aa_contract_model=None,
        model="test-model",
    )
    return DRIFTLLM(args=args, client=object(), logger=None)


def test_reset_task_state_clears_task_local_state():
    llm = make_llm()
    sentinel = object()

    llm.function_trajectory = ["read_file"]
    llm.initial_function_trajectory = ["read_file"]
    llm.achieved_function_trajectory = ["read_file"]
    llm.node_checklist = "[checklist]"
    llm.initial_node_checklist = "[checklist]"
    llm.aa_global_contract = sentinel
    llm.aa_argument_contract = {"trajectory": ["read_file"]}
    llm.aa_provenance_store = object()
    llm.aa_validation_events = [{"passed": True}]

    llm.reset_task_state()

    assert llm.function_trajectory == []
    assert llm.initial_function_trajectory == []
    assert llm.achieved_function_trajectory == []
    assert llm.node_checklist == "None"
    assert llm.initial_node_checklist == "None"
    assert llm.aa_argument_contract is None
    assert llm.aa_provenance_store is None
    assert llm.aa_validation_events == []
    assert llm.aa_global_contract is sentinel


def test_aa_disabled_result_fields_stay_minimal():
    llm = make_llm(enable_argument_authority_drift=False)

    fields = llm.aa_result_fields()

    assert fields["argument_authority_enabled"] is False
    assert fields["aa_diagnostics"]["num_aa_events"] == 0
    assert fields["aa_diagnostics"]["contract_trajectory_matches_initial"] is True
