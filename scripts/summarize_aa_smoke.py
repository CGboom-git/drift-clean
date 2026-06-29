from __future__ import annotations

import argparse
import json
from pathlib import Path


def _safe_get(data, *keys, default="N/A"):
    cur = data
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def _as_text(value):
    if value is None:
        return "N/A"
    if isinstance(value, (list, tuple, set)):
        if not value:
            return "N/A"
        return ", ".join(str(v) for v in value)
    if value == "":
        return "N/A"
    return str(value)


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _count_extra_write_or_execute_calls(data: dict) -> str:
    permissions = data.get("tool_permission")
    conversations = data.get("conversations")
    if not isinstance(permissions, dict) or not isinstance(conversations, list):
        return "N/A"

    count = 0
    for message in conversations:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            tool_name = _safe_get(call, "function", "name", default=None)
            if not tool_name:
                continue
            if permissions.get(tool_name) != "Read":
                count += 1
    return str(count)


def _flatten_reject_reasons(events):
    reasons = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        if event.get("passed") is False:
            reasons.append(str(event.get("reason", "N/A")))
    if not reasons:
        return "N/A"
    return ", ".join(sorted(set(reasons)))


def _fmt_row(values, widths):
    parts = []
    for value, width in zip(values, widths):
        txt = _as_text(value)
        if len(txt) > width:
            txt = txt[: width - 3] + "..."
        parts.append(txt.ljust(width))
    return " | ".join(parts)


def summarize(root: Path) -> int:
    files = sorted(root.rglob("*.json"))
    rows = []
    for path in files:
        data = _load_json(path)
        if not isinstance(data, dict):
            continue

        rows.append(
            {
                "suite": _safe_get(data, "suite_name"),
                "user_task_id": _safe_get(data, "user_task_id"),
                "injection_task_id": _safe_get(data, "injection_task_id"),
                "utility": _safe_get(data, "utility"),
                "security": _safe_get(data, "security"),
                "argument_authority_enabled": _safe_get(data, "argument_authority_enabled"),
                "num_aa_validation_events": len(_safe_get(data, "aa_validation_events", default=[])) if isinstance(_safe_get(data, "aa_validation_events", default=[]), list) else "N/A",
                "num_rejected_tool_calls": _safe_get(data, "aa_decision_summary", "num_rejected_tool_calls"),
                "reject_reasons": _flatten_reject_reasons(_safe_get(data, "aa_validation_events", default=[])),
                "num_provenance_records": len(_safe_get(data, "aa_provenance_records", default=[])) if isinstance(_safe_get(data, "aa_provenance_records", default=[]), list) else "N/A",
                "extra_write_or_execute_calls": _count_extra_write_or_execute_calls(data),
                "path": path,
                "events": _safe_get(data, "aa_validation_events", default=[]),
            }
        )

    if not rows:
        print("No result JSON files found.")
        return 1

    headers = [
        "suite",
        "user_task_id",
        "injection_task_id",
        "utility",
        "security",
        "argument_authority_enabled",
        "num_aa_validation_events",
        "num_rejected_tool_calls",
        "reject_reasons",
        "num_provenance_records",
        "extra_write_or_execute_calls",
        "path",
    ]
    widths = [16, 20, 20, 8, 8, 26, 24, 24, 24, 24, 28, 60]
    print(_fmt_row(headers, widths))
    print("-" * (sum(widths) + (len(widths) - 1) * 3))

    for row in rows:
        print(
            _fmt_row(
                [row[h] for h in headers],
                widths,
            )
        )
        rejected = [event for event in row["events"] if isinstance(event, dict) and event.get("passed") is False]
        if rejected:
            print("  Rejected calls:")
            for event in rejected:
                print(f"    Rejected sink: {_as_text(event.get('sink'))}")
                print(f"    Allowed sources: {_as_text(event.get('allowed_sources'))}")
                print(f"    Actual sources: {_as_text(event.get('actual_sources'))}")
                print(f"    Required proofs: {_as_text(event.get('required_proofs'))}")
                print(f"    Actual proofs: {_as_text(event.get('actual_proofs'))}")
                print(f"    Marks: {_as_text(event.get('actual_marks'))}")
                print(f"    Reason: {_as_text(event.get('reason'))}")
        print()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize AA-DRIFT smoke test results.")
    parser.add_argument("root", nargs="?", default="runs", help="Runs directory to scan.")
    args = parser.parse_args()
    return summarize(Path(args.root))


if __name__ == "__main__":
    raise SystemExit(main())
