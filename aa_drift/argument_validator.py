from .global_contract import get_arg_policy


def _unresolved_sinks(argument_contract: dict) -> set[str]:
    return {
        item.get("sink")
        for item in argument_contract.get("unresolved", [])
        if isinstance(item, dict) and item.get("sink")
    }


def _reject(events: list[dict], event: dict) -> tuple[bool, str, list[dict]]:
    event["passed"] = False
    events.append(event)
    return False, event["reason"], events


def validate_action_arguments(
    tool_name: str,
    arguments: dict,
    argument_contract: dict,
    provenance_store,
    global_contract: dict,
) -> tuple[bool, str, list[dict]]:
    events = []
    tool_policy = global_contract.get(tool_name, {})
    if tool_policy.get("tool_type") != "ACTION":
        return True, "", events

    unresolved = _unresolved_sinks(argument_contract)
    contract_args = argument_contract.get("arguments", {})

    for arg_name, arg_value in (arguments or {}).items():
        policy = get_arg_policy(global_contract, tool_name, arg_name)
        if policy.get("tool_type") != "ACTION":
            continue

        sink = f"{tool_name}.{arg_name}"
        event = {
            "tool": tool_name,
            "argument": arg_name,
            "sink": sink,
            "reason": "",
            "allowed_sources": [],
            "actual_sources": [],
            "required_proofs": [],
            "actual_proofs": [],
            "deny_marks": policy.get("deny_marks", []),
            "actual_marks": [],
        }

        if sink in unresolved:
            return _reject(events, {**event, "reason": "unresolved_sink"})
        if sink not in contract_args:
            return _reject(events, {**event, "reason": "missing_argument_contract"})

        spec = contract_args[sink]
        allowed = set(spec.get("allowed_sources", []))
        required = set(spec.get("required_proofs", []))
        provenance = provenance_store.resolve_value(arg_value)
        actual_sources = set(provenance.get("source_paths", []))
        actual_proofs = set(provenance.get("proofs", []))
        actual_marks = set(provenance.get("marks", []))
        deny_marks = set(policy.get("deny_marks", []))

        event.update(
            {
                "allowed_sources": sorted(allowed),
                "actual_sources": sorted(actual_sources),
                "required_proofs": sorted(required),
                "actual_proofs": sorted(actual_proofs),
                "actual_marks": sorted(actual_marks),
            }
        )

        if not actual_sources or "model.generated" in actual_sources:
            return _reject(events, {**event, "reason": "missing_provenance"})
        if not actual_sources.issubset(allowed):
            return _reject(events, {**event, "reason": "source_not_authorized"})
        if not required.issubset(actual_proofs):
            return _reject(events, {**event, "reason": "required_proof_missing"})
        if actual_marks & deny_marks:
            return _reject(events, {**event, "reason": "deny_mark_hit"})

        event["passed"] = True
        events.append(event)

    return True, "", events
