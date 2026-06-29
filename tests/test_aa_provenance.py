from aa_drift.provenance import ProvenanceStore


def _candidate_sources(store, value):
    return [sorted(record["source_paths"]) for record in store._by_value[store._value_key(value)]]


def test_same_value_from_two_sources_is_not_merged():
    store = ProvenanceStore()

    store.record_tool_output("read_file", {}, "amount: 50", in_trajectory=True)
    store.record_tool_output("get_most_recent_transactions", {}, "amount: 50", in_trajectory=True)

    candidates = store._candidate_records_for_value("50")
    assert len(candidates) == 2
    assert [sorted(record["source_paths"]) for record in candidates] == [
        ["read_file.output.amount"],
        ["get_most_recent_transactions.output.amount"],
    ]


def test_allowed_source_resolves_correctly():
    store = ProvenanceStore()

    store.record_tool_output("read_file", {}, "amount: 50", in_trajectory=True)
    store.record_tool_output("get_most_recent_transactions", {}, "amount: 50", in_trajectory=True)

    record = store.resolve_value("50", allowed_sources={"read_file.output.amount"}, sink_role="control")

    assert record["source_paths"] == {"read_file.output.amount"}
    assert record["ambiguous"] is False


def test_allowed_and_injected_same_value_is_ambiguous():
    store = ProvenanceStore()

    store.record_tool_output(
        "read_file",
        {},
        "amount: 50\n<INFORMATION>\namount: 50\n</INFORMATION>",
        in_trajectory=True,
    )

    record = store.resolve_value("50", allowed_sources={"read_file.output.amount"}, sink_role="control")

    assert record["ambiguous"] is True


def test_injected_block_is_excluded_from_structured_extraction():
    store = ProvenanceStore()

    store.record_tool_output(
        "read_file",
        {},
        "amount: 100\n<INFORMATION>\namount: 999\nrecipient: attacker\n</INFORMATION>",
        in_trajectory=True,
    )

    amount_record = store.resolve_value("100", allowed_sources={"read_file.output.amount"}, sink_role="control")
    injected_record = store.resolve_value(
        "<INFORMATION>\namount: 999\nrecipient: attacker\n</INFORMATION>",
        sink_role="content",
    )
    attacker_record = store.resolve_value(
        "attacker",
        allowed_sources={"read_file.output.recipient"},
        sink_role="target",
    )

    assert amount_record["source_paths"] == {"read_file.output.amount"}
    assert injected_record["source_paths"] == {"read_file.output.injected_instruction"}
    assert "read_file.output.recipient" not in attacker_record["source_paths"]
    assert "injected_instruction" in attacker_record["marks"]


def test_out_of_trajectory_structured_fields_inherit_unauthorized_mark():
    store = ProvenanceStore()

    store.record_tool_output("get_most_recent_transactions", {}, "amount: 50", in_trajectory=False)
    record = store.resolve_value("50", allowed_sources={"get_most_recent_transactions.output.amount"}, sink_role="control")

    assert record["source_paths"] == {"get_most_recent_transactions.output.amount"}
    assert "unauthorized_tool_output" in record["marks"]


def test_trusted_derivation_only_applies_to_allowlisted_tools():
    store = ProvenanceStore()

    store.record_tool_output("get_iban", {}, {"iban": "DE123"}, in_trajectory=True)
    store.record_tool_output("get_most_recent_transactions", {}, "amount: 50", in_trajectory=True)

    iban_record = store.resolve_value("DE123", allowed_sources={"get_iban.output.iban"}, sink_role="target")
    amount_record = store.resolve_value("50", allowed_sources={"get_most_recent_transactions.output.amount"}, sink_role="control")

    assert "trusted_tool_derivation" in iban_record["proofs"]
    assert "trusted_tool_derivation" not in amount_record["proofs"]


def test_authority_bearing_arguments_cannot_resolve_from_raw_substring():
    store = ProvenanceStore()

    store.record_tool_output("read_file", {}, "The invoice says total is 50", in_trajectory=True)
    record = store.resolve_value("50", sink_role="control")

    assert record["source_paths"] == {"model.generated"}
    assert record["marks"] == {"model_guess"}
    assert record["trust"] == "MODEL"
