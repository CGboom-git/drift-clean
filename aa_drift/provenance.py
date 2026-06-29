import json
import re
from collections import defaultdict
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
    "title",
    "start_time",
    "end_time",
    "participants",
    "channel",
    "user",
    "url",
    "address",
    "price",
    "hotel",
    "restaurant",
}

AUTHORITY_BEARING_ROLES = {"target", "control", "credential", "command", "selector"}
TRUSTED_DERIVATION_TOOLS = {"get_iban"}


class ProvenanceStore:
    def __init__(self) -> None:
        self.records = []
        self._by_value = defaultdict(list)
        self._seen_tool_messages = set()
        self._record_counter = 0

    def _next_record_id(self) -> str:
        self._record_counter += 1
        return f"prov-{self._record_counter}"

    def _value_key(self, value) -> str:
        try:
            return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)

    def _candidate_records_for_value(self, value) -> list[dict]:
        candidates = list(self._by_value.get(self._value_key(value), []))
        if candidates:
            return candidates

        value_text = str(value)
        seen_ids = set()
        for key, key_candidates in self._by_value.items():
            for candidate in key_candidates:
                if str(candidate.get("value")) != value_text:
                    continue
                record_id = candidate.get("record_id")
                if record_id in seen_ids:
                    continue
                seen_ids.add(record_id)
                candidates.append(candidate)
        return candidates

    def _normalize_field_name(self, field: str) -> str:
        return str(field).strip().lower().replace("-", "_").replace(" ", "_")

    def _make_record(
        self,
        value,
        source_paths,
        marks=None,
        proofs=None,
        trust="MODEL",
        tool_name=None,
        field=None,
        confidence="model",
        metadata=None,
    ) -> dict:
        return {
            "record_id": self._next_record_id(),
            "value": value,
            "source_paths": set(source_paths or []),
            "marks": set(marks or []),
            "proofs": set(proofs or []),
            "trust": trust,
            "tool_name": tool_name,
            "field": field,
            "confidence": confidence,
            "metadata": metadata or {},
        }

    def _store_record(self, record: dict) -> None:
        self.records.append(record)
        self._by_value[self._value_key(record["value"])].append(record)

    def _public_record(self, record: dict) -> dict:
        public = deepcopy(record)
        public["source_paths"] = sorted(public.get("source_paths", set()))
        public["marks"] = sorted(public.get("marks", set()))
        public["proofs"] = sorted(public.get("proofs", set()))
        return public

    def export_records(self) -> list[dict]:
        return [self._public_record(record) for record in self.records]

    def _add_record(
        self,
        value,
        source_paths,
        marks=None,
        proofs=None,
        trust="MODEL",
        tool_name=None,
        field=None,
        confidence="model",
        metadata=None,
    ) -> None:
        record = self._make_record(
            value=value,
            source_paths=source_paths,
            marks=marks,
            proofs=proofs,
            trust=trust,
            tool_name=tool_name,
            field=field,
            confidence=confidence,
            metadata=metadata,
        )
        self._store_record(record)

    def _is_dangerous_candidate(self, record: dict) -> bool:
        marks = set(record.get("marks", set()))
        return bool(marks & {"injected_instruction", "unauthorized_tool_output", "model_guess"})

    def _default_unresolved(self, value, ambiguous=False, candidates=None) -> dict:
        return {
            "value": value,
            "source_paths": {"model.generated"},
            "marks": {"model_guess"},
            "proofs": set(),
            "trust": "MODEL",
            "ambiguous": ambiguous,
            "candidates": candidates or [],
        }

    def _candidate_result(self, value, record: dict, ambiguous=False, candidates=None) -> dict:
        return {
            "value": value,
            "source_paths": set(record.get("source_paths", set())),
            "marks": set(record.get("marks", set())),
            "proofs": set(record.get("proofs", set())),
            "trust": record.get("trust", "MODEL"),
            "ambiguous": ambiguous,
            "candidates": [self._public_record(item) for item in (candidates or [record])],
        }

    def _split_instruction_blocks(self, text: str) -> tuple[str, list[str]]:
        if not isinstance(text, str) or not text:
            return text, []

        blocks = []
        clean_text = text
        pattern = re.compile(
            r"<(INFORMATION|INSTRUCTION|IMPORTANT)>(.*?)</\1>",
            flags=re.IGNORECASE | re.DOTALL,
        )

        def _replace(match):
            blocks.append(match.group(0).strip())
            return " "

        clean_text = pattern.sub(_replace, clean_text)
        return clean_text.strip(), blocks

    def _extract_json_or_yaml(self, text: str):
        if not isinstance(text, str):
            return text
        stripped = text.strip()
        if not stripped:
            return {}

        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            pass

        if yaml is not None:
            try:
                parsed = yaml.safe_load(stripped)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                pass

        return None

    def _extract_key_value_lines(self, text: str) -> dict:
        fields = {}
        for line in (text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            kv_match = re.match(r"^([A-Za-z][A-Za-z0-9 _-]*)\s*[:=]\s*(.+?)\s*$", line)
            if kv_match:
                field = self._normalize_field_name(kv_match.group(1))
                if field in COMMON_FIELDS:
                    fields[field] = kv_match.group(2).strip()
                continue
            table_match = re.match(r"^([A-Za-z][A-Za-z0-9 _-]*?)\s{2,}(.+?)\s*$", line)
            if table_match:
                field = self._normalize_field_name(table_match.group(1))
                if field in COMMON_FIELDS:
                    fields[field] = table_match.group(2).strip()
        return fields

    def _parse_tool_output(self, tool_output):
        if isinstance(tool_output, (dict, list)):
            return tool_output
        if not isinstance(tool_output, str):
            return tool_output

        parsed = self._extract_json_or_yaml(tool_output)
        if parsed is not None:
            return parsed

        fields = self._extract_key_value_lines(tool_output)
        return fields or tool_output

    def _walk_fields(self, value, prefix=""):
        if isinstance(value, dict):
            for key, item in value.items():
                field = self._normalize_field_name(key)
                path = f"{prefix}.{field}" if prefix else field
                yield from self._walk_fields(item, path)
            return

        if isinstance(value, list):
            for item in value:
                yield from self._walk_fields(item, prefix)
            return

        field = prefix.rsplit(".", 1)[-1]
        if field in COMMON_FIELDS:
            yield field, value

    def _user_explicit_fields(self, user_query: str):
        text = user_query or ""

        for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9 _-]*)\b\s*[:=]\s*([^\n,;]+)", text):
            field = self._normalize_field_name(match.group(1))
            if field not in COMMON_FIELDS:
                continue
            value = match.group(2).strip().strip("\"'")
            if value:
                yield field, value

        for match in re.finditer(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b", text):
            yield "email", match.group(1)

        for match in re.finditer(r"\b([A-Z]{2}[0-9A-Z]{10,30})\b", text):
            yield "iban", match.group(1)

        for match in re.finditer(r"['\"]([^'\"]+\.[A-Za-z0-9]{1,8})['\"]", text):
            yield "file_id", match.group(1)

        amount_patterns = [
            re.compile(r"\bamount\b\s*[:=]\s*(\$?\d+(?:\.\d+)?)", flags=re.IGNORECASE),
            re.compile(r"\$(\d+(?:\.\d+)?)"),
        ]
        for pattern in amount_patterns:
            for match in pattern.finditer(text):
                yield "amount", match.group(1)

        date_patterns = [
            re.compile(r"\bdate\b\s*[:=]\s*([^\n,;]+)", flags=re.IGNORECASE),
            re.compile(r"\b(today|tomorrow)\b", flags=re.IGNORECASE),
            re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
            re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b", flags=re.IGNORECASE),
        ]
        for pattern in date_patterns:
            for match in pattern.finditer(text):
                yield "date", match.group(1) if match.groups() else match.group(0)

    def record_user_explicit(self, user_query: str) -> None:
        seen = set()
        for field, value in self._user_explicit_fields(user_query):
            dedupe_key = (field, str(value))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            self._add_record(
                value=value,
                source_paths={f"user.explicit.{field}"},
                proofs={"user_explicit", "exact_match_to_authorized_source"},
                trust="USER",
                field=field,
                confidence="exact",
            )

    def record_tool_output(
        self,
        tool_name: str,
        tool_args: dict,
        tool_output: str | dict | list,
        in_trajectory: bool,
    ) -> None:
        raw_marks = set()
        raw_trust = "TOOL_OUTPUT" if in_trajectory else "EXTERNAL"
        if isinstance(tool_output, str):
            raw_marks.add("raw_external_content")
            raw_trust = "EXTERNAL"
        if not in_trajectory:
            raw_marks.add("unauthorized_tool_output")

        self._add_record(
            value=tool_output,
            source_paths={f"{tool_name}.output.raw"},
            marks=raw_marks,
            trust=raw_trust,
            tool_name=tool_name,
            field="raw",
            confidence="raw",
        )

        clean_output = tool_output
        if isinstance(tool_output, str):
            clean_output, instruction_blocks = self._split_instruction_blocks(tool_output)
            for block in instruction_blocks:
                self._add_record(
                    value=block,
                    source_paths={f"{tool_name}.output.injected_instruction"},
                    marks={"injected_instruction", "raw_external_content"},
                    proofs=set(),
                    trust="EXTERNAL",
                    tool_name=tool_name,
                    field="injected_instruction",
                    confidence="raw",
                )
                injected_content = re.sub(
                    r"^<(INFORMATION|INSTRUCTION|IMPORTANT)>|</(INFORMATION|INSTRUCTION|IMPORTANT)>$",
                    "",
                    block.strip(),
                    flags=re.IGNORECASE,
                ).strip()
                parsed_injected = self._parse_tool_output(injected_content)
                for field, value in self._walk_fields(parsed_injected):
                    self._add_record(
                        value=value,
                        source_paths={f"{tool_name}.output.injected_instruction"},
                        marks={"injected_instruction", "raw_external_content"},
                        proofs=set(),
                        trust="EXTERNAL",
                        tool_name=tool_name,
                        field=field,
                        confidence="raw",
                    )
        else:
            instruction_blocks = []

        parsed_output = self._parse_tool_output(clean_output)
        field_proofs = {"structured_extraction", "schema_validated_parse"}
        if tool_name in TRUSTED_DERIVATION_TOOLS:
            field_proofs.add("trusted_tool_derivation")

        field_marks = set()
        field_trust = "DELEGATED" if in_trajectory else "TOOL_OUTPUT"
        if not in_trajectory:
            field_marks.add("unauthorized_tool_output")

        for field, value in self._walk_fields(parsed_output):
            self._add_record(
                value=value,
                source_paths={f"{tool_name}.output.{field}"},
                marks=set(field_marks),
                proofs=set(field_proofs),
                trust=field_trust,
                tool_name=tool_name,
                field=field,
                confidence="structured",
                metadata={"injected_blocks": len(instruction_blocks)},
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

            tool_output = message.get("error") if message.get("error") is not None else message.get("content")
            self.record_tool_output(tool_name, tool_args, tool_output, tool_name in trajectory_set)

    def _raw_substring_candidates(self, value) -> list[dict]:
        if not isinstance(value, str):
            return []
        needle = value.strip()
        if not needle:
            return []
        matches = []
        for record in self.records:
            record_value = record.get("value")
            if record.get("confidence") != "raw" or not isinstance(record_value, str):
                continue
            if needle in record_value:
                matches.append(record)
        return matches

    def resolve_value(
        self,
        value,
        allowed_sources: set[str] | None = None,
        sink_role: str | None = None,
    ) -> dict:
        allowed_sources = set(allowed_sources or set())
        candidates = self._candidate_records_for_value(value)

        if len(candidates) == 1:
            return self._candidate_result(value, candidates[0], ambiguous=False, candidates=candidates)

        if len(candidates) > 1:
            allowed_candidates = [
                candidate
                for candidate in candidates
                if set(candidate.get("source_paths", set())) & allowed_sources
            ]
            dangerous_candidates = [candidate for candidate in candidates if self._is_dangerous_candidate(candidate)]

            if len(allowed_candidates) == 1 and not dangerous_candidates:
                return self._candidate_result(value, allowed_candidates[0], ambiguous=False, candidates=candidates)
            if allowed_candidates and dangerous_candidates:
                return self._default_unresolved(value, ambiguous=True, candidates=[self._public_record(item) for item in candidates])
            if len(allowed_candidates) > 1:
                return self._default_unresolved(value, ambiguous=True, candidates=[self._public_record(item) for item in candidates])
            return self._candidate_result(value, candidates[0], ambiguous=False, candidates=candidates)

        sink_role = sink_role or ""
        if sink_role not in AUTHORITY_BEARING_ROLES:
            raw_candidates = self._raw_substring_candidates(value)
            if len(raw_candidates) == 1:
                return self._candidate_result(value, raw_candidates[0], ambiguous=False, candidates=raw_candidates)
            if len(raw_candidates) > 1:
                return self._default_unresolved(value, ambiguous=True, candidates=[self._public_record(item) for item in raw_candidates])

        return self._default_unresolved(value, ambiguous=False, candidates=[])
