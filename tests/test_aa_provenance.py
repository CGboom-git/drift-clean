from aa_drift.provenance import ProvenanceStore


def test_unresolved_value_becomes_model_generated_guess():
    store = ProvenanceStore()

    record = store.resolve_value("unknown")

    assert record["source_paths"] == ["model.generated"]
    assert record["marks"] == ["model_guess"]
    assert record["trust"] == "MODEL"


def test_tool_raw_output_gets_raw_external_content_for_text():
    store = ProvenanceStore()

    store.record_tool_output("read_file", {}, "amount: 10", in_trajectory=True)
    record = store.resolve_value("amount: 10")

    assert "read_file.output.raw" in record["source_paths"]
    assert "raw_external_content" in record["marks"]
    assert record["trust"] == "EXTERNAL"


def test_structured_key_value_field_gets_structured_extraction():
    store = ProvenanceStore()

    store.record_tool_output("read_file", {}, "amount: 10\nsubject: rent", in_trajectory=True)
    record = store.resolve_value("10")

    assert record["source_paths"] == ["read_file.output.amount"]
    assert "structured_extraction" in record["proofs"]
    assert record["trust"] == "DELEGATED"


def test_trusted_derivation_output_gets_trusted_tool_derivation():
    store = ProvenanceStore()

    store.record_tool_output("get_iban", {}, {"iban": "DE123"}, in_trajectory=True)
    record = store.resolve_value("DE123")

    assert record["source_paths"] == ["get_iban.output.iban"]
    assert "structured_extraction" in record["proofs"]
    assert "trusted_tool_derivation" in record["proofs"]
