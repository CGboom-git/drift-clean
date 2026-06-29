import json
import re
from copy import deepcopy

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is in project requirements.
    yaml = None


COMMON_FIELDS = {
    "amount",
    "date",
    "due_date",
    "subject",
    "recipient",
    "name",
    "email",
    "iban",
    "file_id",
    "content",
    "body",
    "message",
}


class ProvenanceStore:
    def __init__(self) -> None:
        self.records = []
        self._by_value = {}
        self._seen_tool_messages = set()

    def _value_key(self, value) -> str:
        try:
            return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)

    def _merge_record(self, value, source_paths, marks=None, proofs=None, trust="MODEL") -> None:
        source_paths = set(source_paths or [])
        marks = set(marks or [])
        proofs = set(proofs or [])
        key = self._value_key(value)

        if key in self._by_value:
            record = self._by_value[key]
            record["source_paths"].update(source_paths)
            record["marks"].update(marks)
            record["proofs"].update(proofs)
            if record["trust"] == "MODEL":
                record["trust"] = trust
            return

        record = {
            "value": value,
            "source_paths": source_paths,
            "marks": marks,
            "proofs": proofs,
            "trust": trust,
        }
        self.records.append(record)
        self._by_value[key] = record

    def _public_record(self, record: dict) -> dict:
        public = deepcopy(record)
        public["source_paths"] = sorted(public.get("source_paths", set()))
        public["marks"] = sorted(public.get("marks", set()))
        public["proofs"] = sorted(public.get("proofs", set()))
        return public

    def export_records(self) -> list[dict]:
        return [self._public_record(record) for record in self.records]

    def record_user_explicit(self, user_query: str) -> None:
        for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9_-]*)\b\s*[:=]\s*([^\n,;]+)", user_query or ""):
            field = match.group(1).strip().lower().replace("-", "_")
            if field not in COMMON_FIELDS:
                continue
            value = match.group(2).strip().strip("\"'")
            if value:
                self._merge_record(
                    value,
                    {f"user.explicit.{field}"},
                    proofs={"user_explicit"},
                    trust="USER",
                )

    def _parse_tool_output(self, tool_output):
        if isinstance(tool_output, (dict, list)):
            return tool_output
        if not isinstance(tool_output, str):
            return tool_output

        text = tool_output.strip()
        if not text:
            return {}

        try:
            return json.loads(text)
        except Exception:
            pass

        if yaml is not None:
            try:
                parsed = yaml.safe_load(text)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                pass

        fields = {}
        for line in text.splitlines():
            match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*[:=]\s*(.+?)\s*$", line)
            if match:
                fields[match.group(1)] = match.group(2)
        return fields or tool_output

    def _walk_fields(self, value, prefix=""):
        if isinstance(value, dict):
            for key, item in value.items():
                field = str(key).lower().replace("-", "_")
                path = f"{prefix}.{field}" if prefix else field
                yield from self._walk_fields(item, path)
        elif isinstance(value, list):
            for item in value:
                yield from self._walk_fields(item, prefix)
        else:
            field = prefix.rsplit(".", 1)[-1]
            if field in COMMON_FIELDS:
                yield field, value

    def _is_trusted_derivation_tool(self, tool_name: str) -> bool:
        return tool_name.startswith(("get_", "lookup_", "search_", "find_"))

    def record_tool_output(
        self,
        tool_name: str,
        tool_args: dict,
        tool_output: str | dict | list,
        in_trajectory: bool,
    ) -> None:
        trust = "TOOL_OUTPUT" if in_trajectory else "EXTERNAL"
        marks = set()
        if isinstance(tool_output, str):
            marks.add("raw_external_content")
            trust = "EXTERNAL"
        if not in_trajectory:
            marks.add("unauthorized_tool_output")

        self._merge_record(
            tool_output,
            {f"{tool_name}.output.raw"},
            marks=marks,
            trust=trust,
        )

        parsed_output = self._parse_tool_output(tool_output)
        field_proofs = {"structured_extraction"}
        if self._is_trusted_derivation_tool(tool_name):
            field_proofs.add("trusted_tool_derivation")

        for field, value in self._walk_fields(parsed_output):
            self._merge_record(
                value,
                {f"{tool_name}.output.{field}"},
                proofs=field_proofs,
                trust="DELEGATED",
            )

    def record_new_tool_outputs(self, messages, trajectory: list[str] | None = None) -> None:
        trajectory_set = set(trajectory or [])
        for message in messages or []:
            if message.get("role") != "tool":
                continue
            tool_call = message.get("tool_call")
            tool_name = message.get("name")
            tool_args = {}
            if tool_call is not None:
                tool_name = tool_name or getattr(tool_call, "function", None)
                tool_args = getattr(tool_call, "args", {}) or {}
            if not tool_name:
                continue

            message_id = message.get("tool_call_id") or getattr(tool_call, "id", None) or id(message)
            if message_id in self._seen_tool_messages:
                continue
            self._seen_tool_messages.add(message_id)

            tool_output = message.get("content")
            if message.get("error") is not None:
                tool_output = message.get("error")
            self.record_tool_output(tool_name, tool_args, tool_output, tool_name in trajectory_set)

    def resolve_value(self, value) -> dict:
        key = self._value_key(value)
        if key in self._by_value:
            return self._public_record(self._by_value[key])

        value_text = str(value)
        for record in self.records:
            if str(record.get("value")) == value_text:
                return self._public_record(record)

        if isinstance(value, str):
            needle = value.strip()
            for record in self.records:
                record_value = record.get("value")
                if isinstance(record_value, str) and needle and needle in record_value:
                    return self._public_record(record)

        return {
            "value": value,
            "source_paths": ["model.generated"],
            "marks": ["model_guess"],
            "proofs": [],
            "trust": "MODEL",
        }
