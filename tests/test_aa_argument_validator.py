from aa_drift.argument_validator import validate_action_arguments
from aa_drift.provenance import ProvenanceStore


def global_contract(deny_marks=None):
    return {
        "send_money": {
            "tool_type": "ACTION",
            "check_mode": "full",
            "args": {
                "amount": {
                    "role": "control",
                    "deny_marks": deny_marks or ["model_guess", "raw_external_content"],
                    "allowed_proofs": ["structured_extraction", "schema_validated_parse"],
                    "check_mode": "full",
                    "tool_type": "ACTION",
                }
            },
        }
    }


def argument_contract(allowed_sources=None, required_proofs=None, unresolved=None):
    if allowed_sources is None:
        allowed_sources = ["read_file.output.amount"]
    if required_proofs is None:
        required_proofs = ["structured_extraction", "schema_validated_parse"]
    return {
        "trajectory": ["read_file", "send_money"],
        "arguments": {
            "send_money.amount": {
                "allowed_sources": allowed_sources,
                "required_proofs": required_proofs,
            }
        },
        "unresolved": unresolved or [],
    }


def store_with_amount():
    store = ProvenanceStore()
    store.record_tool_output("read_file", {}, "amount: 10", in_trajectory=True)
    return store


def test_authorized_source_passes():
    ok, reason, events = validate_action_arguments(
        "send_money",
        {"amount": "10"},
        argument_contract(),
        store_with_amount(),
        global_contract(),
    )

    assert ok is True
    assert reason == ""
    assert events[0]["passed"] is True


def test_unauthorized_source_fails():
    ok, reason, events = validate_action_arguments(
        "send_money",
        {"amount": "10"},
        argument_contract(allowed_sources=["user.explicit.amount"]),
        store_with_amount(),
        global_contract(),
    )

    assert ok is False
    assert reason == "source_not_authorized"
    assert events[0]["passed"] is False


def test_missing_required_proof_fails():
    ok, reason, events = validate_action_arguments(
        "send_money",
        {"amount": "10"},
        argument_contract(required_proofs=["structured_extraction", "schema_validated_parse", "trusted_tool_derivation"]),
        store_with_amount(),
        global_contract(),
    )

    assert ok is False
    assert reason == "required_proof_missing"
    assert events[0]["passed"] is False


def test_deny_mark_fails():
    store = ProvenanceStore()
    store.record_tool_output("read_file", {}, "amount: 10", in_trajectory=True)

    ok, reason, events = validate_action_arguments(
        "send_money",
        {"amount": "amount: 10"},
        argument_contract(allowed_sources=["read_file.output.raw"], required_proofs=[]),
        store,
        global_contract(deny_marks=["raw_external_content"]),
    )

    assert ok is False
    assert reason == "deny_mark_hit"
    assert events[0]["passed"] is False


def test_unresolved_sink_fails():
    ok, reason, events = validate_action_arguments(
        "send_money",
        {"amount": "10"},
        {
            "trajectory": ["read_file", "send_money"],
            "arguments": {},
            "unresolved": [{"sink": "send_money.amount", "reason": "uncertain"}],
        },
        store_with_amount(),
        global_contract(),
    )

    assert ok is False
    assert reason == "unresolved_sink"
    assert events[0]["passed"] is False


def test_validator_rejects_ambiguous_provenance():
    store = ProvenanceStore()
    store.record_tool_output(
        "read_file",
        {},
        "amount: 10\n<INFORMATION>\namount: 10\n</INFORMATION>",
        in_trajectory=True,
    )

    ok, reason, events = validate_action_arguments(
        "send_money",
        {"amount": "10"},
        argument_contract(),
        store,
        global_contract(),
    )

    assert ok is False
    assert reason == "ambiguous_provenance"
    assert events[0]["passed"] is False
