from aa_drift.argument_contract import build_argument_contract, summarize_argument_contract, validate_argument_contract


class FailingClient:
    def llm_run(self, *args, **kwargs):
        raise RuntimeError("boom")


def sample_global_contract():
    return {
        "read_file": {
            "tool_type": "READ_SENSITIVE",
            "check_mode": "control_check_and_track",
            "args": {},
        },
        "send_money": {
            "tool_type": "ACTION",
            "check_mode": "full",
            "args": {
                "amount": {
                    "role": "control",
                    "deny_marks": ["model_guess"],
                    "allowed_proofs": ["user_explicit", "structured_extraction"],
                    "check_mode": "full",
                    "tool_type": "ACTION",
                },
                "recipient": {
                    "role": "target",
                    "deny_marks": ["raw_external_content"],
                    "allowed_proofs": ["structured_extraction", "trusted_tool_derivation"],
                    "check_mode": "full",
                    "tool_type": "ACTION",
                },
            },
        },
    }


def test_contract_without_depends_on_tool_passes():
    contract = {
        "trajectory": ["read_file", "send_money"],
        "arguments": {
            "send_money.amount": {
                "allowed_sources": ["read_file.output.amount"],
                "required_proofs": ["structured_extraction"],
            }
        },
        "unresolved": [{"sink": "send_money.recipient", "reason": "uncertain"}],
    }

    ok, reason = validate_argument_contract(contract, ["read_file", "send_money"], sample_global_contract())

    assert ok is True
    assert reason == ""


def test_source_outside_trajectory_fails():
    contract = {
        "trajectory": ["read_file", "send_money"],
        "arguments": {
            "send_money.amount": {
                "allowed_sources": ["get_most_recent_transactions.output.amount"],
                "required_proofs": ["structured_extraction"],
            }
        },
        "unresolved": [],
    }

    ok, reason = validate_argument_contract(contract, ["read_file", "send_money"], sample_global_contract())

    assert ok is False
    assert reason.startswith("source_tool_outside_trajectory")


def test_required_proof_not_allowed_fails():
    contract = {
        "trajectory": ["read_file", "send_money"],
        "arguments": {
            "send_money.amount": {
                "allowed_sources": ["read_file.output.amount"],
                "required_proofs": ["trusted_tool_derivation"],
            }
        },
        "unresolved": [],
    }

    ok, reason = validate_argument_contract(contract, ["read_file", "send_money"], sample_global_contract())

    assert ok is False
    assert reason.startswith("required_proof_not_allowed")


def test_resolved_and_unresolved_same_sink_fails():
    contract = {
        "trajectory": ["read_file", "send_money"],
        "arguments": {
            "send_money.amount": {
                "allowed_sources": ["read_file.output.amount"],
                "required_proofs": ["structured_extraction"],
            }
        },
        "unresolved": [{"sink": "send_money.amount", "reason": "uncertain"}],
    }

    ok, reason = validate_argument_contract(contract, ["read_file", "send_money"], sample_global_contract())

    assert ok is False
    assert reason.startswith("sink_both_resolved_and_unresolved")


def test_extra_argument_fields_are_rejected():
    contract = {
        "trajectory": ["read_file", "send_money"],
        "arguments": {
            "send_money.amount": {
                "depends_on_tool": "read_file",
                "allowed_sources": ["read_file.output.amount"],
                "required_proofs": ["structured_extraction"],
            }
        },
        "unresolved": [],
    }

    ok, reason = validate_argument_contract(contract, ["read_file", "send_money"], sample_global_contract())

    assert ok is False
    assert reason.startswith("unexpected_argument_spec_field")


def test_unresolved_sink_is_accepted():
    contract = {
        "trajectory": ["read_file", "send_money"],
        "arguments": {},
        "unresolved": [{"sink": "send_money.amount", "reason": "no source"}],
    }

    ok, reason = validate_argument_contract(contract, ["read_file", "send_money"], sample_global_contract())

    assert ok is True
    assert reason == ""


def test_fallback_includes_user_explicit_sources_without_depends_on_tool():
    contract = build_argument_contract(
        client=FailingClient(),
        model="test",
        user_query="Please send amount: 19.50 to the account.",
        trajectory=["read_file", "send_money"],
        tool_schemas=[],
        global_contract_subset=sample_global_contract(),
    )

    spec = contract["arguments"]["send_money.amount"]
    assert set(spec) == {"allowed_sources", "required_proofs"}
    assert spec["allowed_sources"] == ["user.explicit.amount"]


def test_summary_omits_depends_on_tool():
    contract = {
        "trajectory": ["read_file", "send_money"],
        "arguments": {
            "send_money.amount": {
                "allowed_sources": ["read_file.output.amount"],
                "required_proofs": ["structured_extraction"],
            }
        },
        "unresolved": [],
    }

    summary = summarize_argument_contract(contract)

    assert summary["arguments"]["send_money.amount"] == {
        "allowed_sources": ["read_file.output.amount"],
        "required_proofs": ["structured_extraction"],
    }
