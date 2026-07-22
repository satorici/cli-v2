"""Shape-agnostic fallback parser for unknown tools' JSON stdout.

Faithful port of web/src/lib/utils/parsers/dynamic.ts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, Union

TemplateSeverity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", "BLOCKER"]

SEVERITIES: list[TemplateSeverity] = [
    "INFO",
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
    "BLOCKER",
]

MAX_INPUT_CHARS = 2_000_000
MAX_WALK_DEPTH = 5
MAX_WALK_ELEMENTS = 50
FLATTEN_DEPTH = 4
MAX_LEAVES = 40
MAX_FIELDS = 25
MAX_VALUE_CHARS = 500
MAX_RECORDS = 500
MAX_PARENT_FIELDS = 10
SCORE_SAMPLE = 25
MAX_JOINED_ITEMS = 20

URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)
TIMESTAMP_TITLE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")
ALPHABETIC_TOKEN_RE = re.compile(r"[a-z]+")

Primitive = Union[str, int, float, bool]
JsonRecord = dict[str, Any]


@dataclass
class DynamicFinding:
    title: str
    fields: dict[str, str] = field(default_factory=dict)
    severity: Optional[str] = None
    id: Optional[str] = None
    location: Optional[str] = None
    line: Optional[int] = None
    description: Optional[str] = None
    url: Optional[str] = None


@dataclass
class _CandidateRecord:
    value: JsonRecord
    parents: list[JsonRecord]
    map_key: Optional[str] = None


@dataclass
class _CandidateGroup:
    depth: int
    records: list[_CandidateRecord]


@dataclass
class _Leaf:
    display: str
    norm: str
    value: Primitive
    kind: Literal["scalar", "joined", "summary"]


SKIP_KEYS = frozenset({"__proto__", "constructor", "prototype"})

TITLE_KEYS = (
    "title",
    "name",
    "alert",
    "message",
    "msg",
    "summary",
    "checkname",
    "rulename",
    "rule",
    "finding",
    "issue",
    "key",
)
SEVERITY_KEYS = (
    "severity",
    "level",
    "risk",
    "riskdesc",
    "priority",
    "impact",
    "criticality",
    "threat",
)
ID_KEYS = (
    "ruleid",
    "checkid",
    "testid",
    "templateid",
    "vulnerabilityid",
    "cveid",
    "cve",
    "pluginid",
    "id",
    "code",
)
LOCATION_KEYS = (
    "file",
    "filename",
    "path",
    "filepath",
    "target",
    "host",
    "url",
    "uri",
    "matchedat",
    "location",
    "resource",
)
LINE_KEYS = ("line", "linenumber", "startline", "beginline", "lineno")
DESCRIPTION_KEYS = ("description", "desc", "details", "detail", "info", "text")
URL_KEYS = ("reference", "link", "moreinfo", "helpuri", "infourl", "datasource")

SEVERITY_WORD_TO_TEMPLATE: dict[str, TemplateSeverity] = {
    "blocker": "BLOCKER",
    "critical": "CRITICAL",
    "crit": "CRITICAL",
    "fatal": "CRITICAL",
    "high": "HIGH",
    "error": "HIGH",
    "severe": "HIGH",
    "important": "HIGH",
    "medium": "MEDIUM",
    "moderate": "MEDIUM",
    "warning": "MEDIUM",
    "warn": "MEDIUM",
    "low": "LOW",
    "minor": "LOW",
    "info": "INFO",
    "informational": "INFO",
    "informative": "INFO",
    "note": "INFO",
    "style": "INFO",
    "none": "INFO",
    "negligible": "INFO",
}


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _is_primitive(value: Any) -> bool:
    # Match JS typeof for string/number/boolean.
    return isinstance(value, (str, int, float, bool))


def _try_json_parse(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_json(
    text: str,
) -> Optional[tuple[Literal["single"], Any] | tuple[Literal["jsonl"], list[JsonRecord]]]:
    whole = _try_json_parse(text)
    if whole is not None:
        if _is_record(whole) or isinstance(whole, list):
            return ("single", whole)
        return None

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    first_object_line = next(
        (i for i, line in enumerate(lines) if line.startswith("{")), -1
    )
    if first_object_line != -1:
        candidates = lines[first_object_line:]
        if len(candidates) >= 2:
            records = [
                parsed
                for parsed in (_try_json_parse(line) for line in candidates)
                if _is_record(parsed)
            ]
            if len(records) >= 2 and len(records) / len(candidates) >= 0.8:
                return ("jsonl", records)

    attempts: list[tuple[int, int]] = []
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        attempts.append((brace_start, brace_end))
    bracket_start = text.find("[")
    bracket_end = text.rfind("]")
    if bracket_start != -1 and bracket_end > bracket_start:
        attempts.append((bracket_start, bracket_end))
    attempts.sort(key=lambda pair: pair[0])
    for start, end in attempts:
        sliced = _try_json_parse(text[start : end + 1])
        if _is_record(sliced) or isinstance(sliced, list):
            return ("single", sliced)

    return None


def _is_homogeneous_map(entries: list[tuple[str, Any]]) -> bool:
    if len(entries) < 2:
        return False
    if not all(_is_record(value) for _, value in entries):
        return False
    key_sets = [set(value.keys()) for _, value in entries]
    min_size = min(len(keys) for keys in key_sets)
    if min_size == 0:
        return False
    first, *rest = key_sets
    shared = sum(1 for key in first if all(key in keys for keys in rest))
    return shared / min_size >= 0.5


def _collect_candidates(root: Any) -> list[_CandidateGroup]:
    groups: dict[str, _CandidateGroup] = {}

    def group_for(path: list[str], marker: str) -> _CandidateGroup:
        key = "/".join(path) + marker
        group = groups.get(key)
        if group is None:
            group = _CandidateGroup(depth=len(path), records=[])
            groups[key] = group
        return group

    def walk(
        value: Any,
        path: list[str],
        ancestors: list[JsonRecord],
        depth: int,
    ) -> None:
        if depth > MAX_WALK_DEPTH:
            return

        if isinstance(value, list):
            if len(value) >= 1 and all(item is None or _is_record(item) for item in value):
                records = [item for item in value if _is_record(item)]
                if records:
                    group = group_for(path, "[]")
                    for record in records:
                        group.records.append(
                            _CandidateRecord(value=record, parents=list(ancestors))
                        )
            for item in value[:MAX_WALK_ELEMENTS]:
                walk(item, path, ancestors, depth + 1)
            return

        if not _is_record(value):
            return
        entries = list(value.items())
        is_map = _is_homogeneous_map(entries)
        if is_map:
            group = group_for(path, "{}")
            for map_key, item in entries:
                group.records.append(
                    _CandidateRecord(
                        value=item, parents=list(ancestors), map_key=map_key
                    )
                )
        next_ancestors = [*ancestors, value]
        for key, item in entries:
            if isinstance(item, list) or _is_record(item):
                walk(
                    item,
                    [*path, "*" if is_map else key],
                    next_ancestors,
                    depth + 1,
                )

    walk(root, [], [], 0)
    return list(groups.values())


def _richness(record: JsonRecord) -> int:
    count = 0

    def descend(value: JsonRecord, depth: int) -> None:
        nonlocal count
        for item in value.values():
            if count >= SCORE_SAMPLE:
                return
            if _is_primitive(item):
                count += 1
            elif isinstance(item, list):
                if len(item) > 0 and all(_is_primitive(x) for x in item):
                    count += 1
            elif _is_record(item) and depth + 1 < FLATTEN_DEPTH:
                descend(item, depth + 1)

    descend(record, 0)
    return count


def _score_group(group: _CandidateGroup) -> float:
    sample = group.records[:SCORE_SAMPLE]
    if not sample:
        return 0
    total = sum(_richness(record.value) for record in sample)
    return len(group.records) * (total / len(sample))


def _pick_best_group(groups: list[_CandidateGroup]) -> Optional[_CandidateGroup]:
    best: Optional[_CandidateGroup] = None
    best_score = 0.0
    for group in groups:
        score = _score_group(group)
        if score <= 0:
            continue
        if (
            best is None
            or score > best_score
            or (score == best_score and group.depth < best.depth)
        ):
            best = group
            best_score = score
    return best


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _flatten_record(record: JsonRecord) -> list[_Leaf]:
    leaves: list[_Leaf] = []

    def recurse(value: JsonRecord, segments: list[str]) -> None:
        for key, item in value.items():
            if len(leaves) >= MAX_LEAVES:
                return
            if key in SKIP_KEYS:
                continue
            if item is None:
                continue
            if isinstance(item, str) and item.strip() == "":
                continue
            path = [*segments, key]
            if _is_primitive(item):
                leaves.append(
                    _Leaf(
                        display=".".join(path),
                        norm=_normalize_key(key),
                        value=item,
                        kind="scalar",
                    )
                )
            elif isinstance(item, list):
                if len(item) == 0:
                    continue
                if all(_is_primitive(x) for x in item):
                    leaves.append(
                        _Leaf(
                            display=".".join(path),
                            norm=_normalize_key(key),
                            value=", ".join(str(x) for x in item[:MAX_JOINED_ITEMS]),
                            kind="joined",
                        )
                    )
                else:
                    leaves.append(
                        _Leaf(
                            display=".".join(path),
                            norm=_normalize_key(key),
                            value=f"[{len(item)} items]",
                            kind="summary",
                        )
                    )
            elif (
                _is_record(item)
                and len(item) > 0
                and len(path) < FLATTEN_DEPTH
            ):
                recurse(item, path)

    recurse(record, [])
    return leaves


def _parent_context_leaves(
    candidate: _CandidateRecord, own_norms: set[str]
) -> list[_Leaf]:
    extras: list[_Leaf] = []
    seen = set(own_norms)
    if candidate.map_key is not None and "key" not in seen:
        extras.append(
            _Leaf(display="key", norm="key", value=candidate.map_key, kind="scalar")
        )
        seen.add("key")
    added = 0
    for i in range(len(candidate.parents) - 1, -1, -1):
        for key, value in candidate.parents[i].items():
            if added >= MAX_PARENT_FIELDS:
                return extras
            if key in SKIP_KEYS:
                continue
            if not _is_primitive(value):
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            norm = _normalize_key(key)
            if norm in seen:
                continue
            extras.append(_Leaf(display=key, norm=norm, value=value, kind="scalar"))
            seen.add(norm)
            added += 1
    return extras


def _is_prose_like(value: str) -> bool:
    trimmed = value.strip()
    if len(trimmed) < 3 or len(trimmed) > 120:
        return False
    if TIMESTAMP_TITLE_RE.match(trimmed):
        return False
    return " " in trimmed or len(trimmed) >= 12


def _truncate_value(value: str) -> str:
    if len(value) > MAX_VALUE_CHARS:
        return f"{value[:MAX_VALUE_CHARS]}…"
    return value


def _js_number(value: Any) -> float:
    """Approximate JS Number() for line binding."""
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return float("nan")
    return float("nan")


def _to_dynamic_finding(candidate: _CandidateRecord) -> Optional[DynamicFinding]:
    own = _flatten_record(candidate.value)
    own_norms = {leaf.norm for leaf in own}
    pool = [*own, *_parent_context_leaves(candidate, own_norms)]
    consumed: set[int] = set()

    def bind(
        keys: tuple[str, ...],
        accept: Optional[Callable[[_Leaf], bool]] = None,
    ) -> Optional[_Leaf]:
        for key in keys:
            for idx, leaf in enumerate(pool):
                if idx in consumed or leaf.kind != "scalar" or leaf.norm != key:
                    continue
                if accept is not None and not accept(leaf):
                    continue
                consumed.add(idx)
                return leaf
        return None

    title_leaf = bind(TITLE_KEYS, lambda leaf: len(str(leaf.value)) > 0)
    severity_leaf = bind(SEVERITY_KEYS)
    id_leaf = bind(ID_KEYS)
    location_leaf = bind(LOCATION_KEYS)

    def accept_line(leaf: _Leaf) -> bool:
        line = _js_number(leaf.value)
        return line == line and line.is_integer() and line > 0

    line_leaf = bind(LINE_KEYS, accept_line)
    description_leaf = bind(DESCRIPTION_KEYS, lambda leaf: isinstance(leaf.value, str))
    url_by_key = bind(
        URL_KEYS,
        lambda leaf: isinstance(leaf.value, str) and bool(URL_PATTERN.match(leaf.value)),
    )
    url_leaf = url_by_key
    if url_leaf is None:
        for idx, leaf in enumerate(pool):
            if (
                idx not in consumed
                and leaf.kind == "scalar"
                and isinstance(leaf.value, str)
                and URL_PATTERN.match(leaf.value)
            ):
                consumed.add(idx)
                url_leaf = leaf
                break

    if title_leaf is not None:
        title = str(title_leaf.value)
    else:
        prose: Optional[_Leaf] = None
        prose_idx: Optional[int] = None
        for idx, leaf in enumerate(pool):
            if (
                idx not in consumed
                and leaf.kind == "scalar"
                and isinstance(leaf.value, str)
                and _is_prose_like(leaf.value)
            ):
                prose = leaf
                prose_idx = idx
                break
        if prose is not None and prose_idx is not None:
            consumed.add(prose_idx)
            title = str(prose.value)
        elif id_leaf is not None:
            title = str(id_leaf.value)
        elif location_leaf is not None:
            title = str(location_leaf.value)
        else:
            title = "Finding"

    field_pairs: list[tuple[str, str]] = []
    for idx, leaf in enumerate(pool):
        if idx in consumed:
            continue
        if len(field_pairs) >= MAX_FIELDS:
            break
        field_pairs.append((leaf.display, _truncate_value(str(leaf.value))))

    key_bound_count = sum(
        1
        for leaf in (
            title_leaf,
            severity_leaf,
            id_leaf,
            location_leaf,
            line_leaf,
            description_leaf,
            url_by_key,
        )
        if leaf is not None
    )
    if key_bound_count == 0 and len(field_pairs) < 2:
        return None

    return DynamicFinding(
        title=_truncate_value(title),
        severity=str(severity_leaf.value) if severity_leaf else None,
        id=str(id_leaf.value) if id_leaf else None,
        location=str(location_leaf.value) if location_leaf else None,
        line=int(_js_number(line_leaf.value)) if line_leaf else None,
        description=(
            _truncate_value(str(description_leaf.value)) if description_leaf else None
        ),
        url=str(url_leaf.value) if url_leaf else None,
        fields=dict(field_pairs),
    )


def dynamic_severity_to_template(
    severity: Optional[str],
) -> Optional[TemplateSeverity]:
    """Map the first alphabetic token of a severity string to the template scale."""
    if not severity:
        return None
    match = ALPHABETIC_TOKEN_RE.search(severity.lower())
    if not match:
        return None
    token = match.group(0)
    return SEVERITY_WORD_TO_TEMPLATE.get(token)


def _severity_rank(finding: DynamicFinding) -> int:
    mapped = dynamic_severity_to_template(finding.severity)
    if mapped is None:
        return -1
    return SEVERITIES.index(mapped)


def parse_dynamic_output(stdout: Optional[str]) -> Optional[list[DynamicFinding]]:
    """Parse unknown-tool JSON stdout into best-effort findings.

    Returns ``None`` (never ``[]``) when nothing informative is found.
    """
    if not stdout or len(stdout) > MAX_INPUT_CHARS:
        return None
    text = stdout.lstrip("\ufeff").strip()
    if not text:
        return None

    extracted = _extract_json(text)
    if extracted is None:
        return None

    kind, payload = extracted
    if kind == "jsonl":
        candidates = [
            _CandidateRecord(value=value, parents=[]) for value in payload
        ]
    else:
        best = _pick_best_group(_collect_candidates(payload))
        if best is None:
            return None
        candidates = best.records

    findings = [
        finding
        for finding in (
            _to_dynamic_finding(candidate)
            for candidate in candidates[:MAX_RECORDS]
        )
        if finding is not None
    ]
    if not findings:
        return None

    findings.sort(key=_severity_rank, reverse=True)
    return findings
