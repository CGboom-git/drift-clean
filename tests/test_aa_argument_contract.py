from aa_drift.argument_contract import build_argument_contract, validate_argument_contract


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


def test_contract_only_references_tools_in_trajectory_and_valid_sink():
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


def test_contract_rejects_source_tool_outside_trajectory():
    contract = {
        "trajectory": ["read_file", "send_money"],
        "arguments": {
            "send_money.amount": {
                "allowed_sources": ["search_email.output.amount"],
                "required_proofs": ["structured_extraction"],
            }
        },
        "unresolved": [],
    }

    ok, reason = validate_argument_contract(contract, ["read_file", "send_money"], sample_global_contract())

    assert ok is False
    assert reason.startswith("source_tool_outside_trajectory")


def test_contract_rejects_required_proof_not_allowed_by_policy():
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


def test_unresolved_sink_is_accepted():
    contract = {
        "trajectory": ["read_file", "send_money"],
        "arguments": {},
        "unresolved": [{"sink": "send_money.amount", "reason": "no source"}],
    }

    ok, reason = validate_argument_contract(contract, ["read_file", "send_money"], sample_global_contract())

    assert ok is True
    assert reason == ""


def test_fallback_does_not_invent_sources():
    contract = build_argument_contract(
        client=FailingClient(),
        model="test",
        user_query="Please pay the bill from the file.",
        trajectory=["read_file", "send_money"],
        tool_schemas=[],
        global_contract_subset=sample_global_contract(),
    )

    assert contract["arguments"] == {}
    assert {item["sink"] for item in contract["unresolved"]} == {
        "send_money.amount",
        "send_money.recipient",
    }
