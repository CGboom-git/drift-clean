import json
from pathlib import Path


DEFAULT_POLICY = {
    "role": "",
    "deny_marks": [],
    "allowed_proofs": [],
    "check_mode": "",
    "tool_type": "",
}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_arg_policy(tool_policy: dict, arg_policy: dict) -> dict:
    return {
        "role": arg_policy.get("role") or arg_policy.get("sink_role") or "",
        "deny_marks": _as_list(arg_policy.get("F", arg_policy.get("deny_marks", []))),
        "allowed_proofs": _as_list(arg_policy.get("D", arg_policy.get("endorsements", []))),
        "check_mode": tool_policy.get("check_mode", arg_policy.get("check_mode", "")),
        "tool_type": tool_policy.get("tool_type", arg_policy.get("tool_type", "")),
    }


def _normalize_contract(raw_contract: dict) -> dict:
    raw_tools = raw_contract.get("tools", raw_contract)
    normalized = {}

    for tool_name, tool_policy in raw_tools.items():
        if not isinstance(tool_policy, dict):
            continue

        if "." in tool_name and (
            "role" in tool_policy
            or "sink_role" in tool_policy
            or "F" in tool_policy
            or "deny_marks" in tool_policy
        ):
            flat_tool_name, arg_name = tool_name.split(".", 1)
            tool_entry = normalized.setdefault(
                flat_tool_name,
                {
                    "tool_name": flat_tool_name,
                    "tool_type": tool_policy.get("tool_type", ""),
                    "check_mode": tool_policy.get("check_mode", ""),
                    "args": {},
                },
            )
            tool_entry["args"][arg_name] = _normalize_arg_policy(tool_policy, tool_policy)
            continue

        args = tool_policy.get("args")
        if args is None:
            args = tool_policy.get("arguments", {})
        if not args and any(
            isinstance(value, dict)
            and (
                "role" in value
                or "sink_role" in value
                or "F" in value
                or "deny_marks" in value
            )
            for value in tool_policy.values()
        ):
            args = {
                key: value
                for key, value in tool_policy.items()
                if isinstance(value, dict)
                and (
                    "role" in value
                    or "sink_role" in value
                    or "F" in value
                    or "deny_marks" in value
                )
            }
        if not isinstance(args, dict):
            args = {}

        normalized_args = {}
        for arg_name, arg_policy in args.items():
            if not isinstance(arg_policy, dict):
                arg_policy = {}
            normalized_args[arg_name] = _normalize_arg_policy(tool_policy, arg_policy)

        normalized[tool_name] = {
            "tool_name": tool_policy.get("tool_name", tool_name),
            "tool_type": tool_policy.get("tool_type", ""),
            "check_mode": tool_policy.get("check_mode", ""),
            "args": normalized_args,
        }

    return normalized


def load_global_contract(path: str) -> dict:
    with Path(path).open("r", encoding="utf-8") as f:
        raw_contract = json.load(f)
    return _normalize_contract(raw_contract)


def get_arg_policy(global_contract: dict, tool_name: str, arg_name: str) -> dict:
    tool_policy = global_contract.get(tool_name, {})
    arg_policy = tool_policy.get("args", {}).get(arg_name)
    if arg_policy is None:
        return {
            **DEFAULT_POLICY,
            "check_mode": tool_policy.get("check_mode", ""),
            "tool_type": tool_policy.get("tool_type", ""),
        }
    return {
        **DEFAULT_POLICY,
        **arg_policy,
    }
