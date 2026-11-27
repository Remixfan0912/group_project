"""Module 1: Recursive-descent Parser & AST Builder for Pretty Sequence Diagrams.

Parses SBC Revised Process Algebra expressions together with an 8-Field Guarded
Interaction Table (GIT) into the standardized Intermediate AST & Lifelines JSON
defined in ``schema.json`` (version 1.0).

Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import csv
from dataclasses import dataclass
import io
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "1.0"

SMD_ATTRIBUTES = frozenset({"defer", "invariant"})
AD_ATTRIBUTES = frozenset(
    {"swimlanes", "inlane", "interrupt", "catch", "activityFinal"}
)
CONTROL_ATTRIBUTES = frozenset({"fork", "join"})

COMBINED_FRAGMENT_KINDS = frozenset(
    {
        "alt",
        "par",
        "opt",
        "loop",
        "break",
        "neg",
        "critical",
        "assert",
        "ignore",
        "consider",
    }
)
FRAMED_SEQUENCE_KINDS = frozenset({"strict", "seq"})
VALID_NATURES = frozenset({"call", "return", "combined"})
VALID_LIFELINE_ROLES = frozenset(
    {"participant", "actor", "boundary", "control", "entity", "database"}
)


class ParseError(ValueError):
    """Raised when a Process Algebra expression or GIT table cannot be parsed."""

    def __init__(
        self,
        message: str,
        position: int | None = None,
        source: str | None = None,
    ) -> None:
        self.message = message
        self.position = position
        self.source = source
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.position is None:
            return self.message
        if not self.source:
            return f"{self.message} (at offset {self.position})"
        pos = max(0, min(self.position, len(self.source)))
        line_start = self.source.rfind("\n", 0, pos) + 1
        line_end = self.source.find("\n", pos)
        if line_end == -1:
            line_end = len(self.source)
        line_num = self.source.count("\n", 0, pos) + 1
        col_num = pos - line_start + 1
        line_text = self.source[line_start:line_end]
        caret = " " * (col_num - 1) + "^"
        return (
            f"{self.message} (line {line_num}, col {col_num})\n"
            f"  {line_text}\n"
            f"  {caret}"
        )


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    start: int
    end: int


def _split_top_level(text: str, delimiter: str = ",") -> list[str]:
    """Split ``text`` by ``delimiter`` ignoring delimiters inside nested brackets."""
    parts: list[str] = []
    current: list[str] = []
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    quote: str | None = None

    for ch in text:
        if quote is not None:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
        elif ch == "(":
            paren_depth += 1
            current.append(ch)
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
            current.append(ch)
        elif ch == "[":
            bracket_depth += 1
            current.append(ch)
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
            current.append(ch)
        elif ch == "{":
            brace_depth += 1
            current.append(ch)
        elif ch == "}":
            brace_depth = max(0, brace_depth - 1)
            current.append(ch)
        elif (
            ch == delimiter
            and paren_depth == 0
            and bracket_depth == 0
            and brace_depth == 0
        ):
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    tail = "".join(current).strip()
    if tail or parts:
        parts.append(tail)
    return [p for p in parts if p]


def _normalize_param_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text or text in ("-", "∅", "none", "None"):
        return []
    return _split_top_level(text, ",")


def _strip_outer_brackets(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) >= 2 and cleaned.startswith("[") and cleaned.endswith("]"):
        return cleaned[1:-1].strip()
    return cleaned


def format_interaction_label(
    guard: str,
    operation: str,
    inputs: Sequence[str],
    outputs: Sequence[str],
    nature: str = "call",
) -> str:
    """Format a UML message label: ``[Guard] operation(in1, in2): out1``."""
    prefix = f"[{guard}] " if guard else ""
    in_str = ", ".join(inputs)
    out_str = ", ".join(outputs)

    if operation:
        base = f"{operation}({in_str})"
        if out_str:
            return f"{prefix}{base}: {out_str}"
        return f"{prefix}{base}"

    if nature == "return" and out_str:
        return f"{prefix}{out_str}"
    if in_str and out_str:
        return f"{prefix}({in_str}): {out_str}"
    if out_str:
        return f"{prefix}{out_str}"
    if in_str:
        return f"{prefix}({in_str})"
    return prefix.strip()


def _pick_field(row: Mapping[str, Any], aliases: Sequence[str], default: Any = "") -> Any:
    for key in aliases:
        if key in row and row[key] is not None:
            return row[key]
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in aliases:
        lk = key.lower()
        if lk in lowered and lowered[lk] is not None:
            return lowered[lk]
    return default


def _normalize_git_entry(interaction_id: str, raw: Any) -> dict[str, Any]:
    """Normalize a single 8-field GIT entry into the schema.json GitInteraction dict."""
    iid = str(interaction_id).strip()
    if not iid:
        raise ParseError("GIT interaction id must be a non-empty string")

    if isinstance(raw, (list, tuple)):
        if len(raw) != 8:
            raise ParseError(
                f"GIT tuple for '{iid}' must have exactly 8 fields "
                f"(C, Xi, N, Gamma, Lambda, Theta_in, Theta_out, Pi); got {len(raw)}"
            )
        guard_raw, caller_raw, nature_raw, callee_raw, op_raw, in_raw, out_raw, act_raw = raw
    elif isinstance(raw, Mapping):
        guard_raw = _pick_field(raw, ("guard", "C", "condition"), "")
        caller_raw = _pick_field(raw, ("caller", "Xi", "xi", "Ξ", "from", "source"), "")
        nature_raw = _pick_field(raw, ("nature", "N", "kind", "type"), "call")
        callee_raw = _pick_field(raw, ("callee", "Gamma", "gamma", "Γ", "to", "target"), "")
        op_raw = _pick_field(raw, ("operation", "Lambda", "lambda", "Λ", "method", "message"), "")
        in_raw = _pick_field(
            raw, ("inputs", "Theta_in", "theta_in", "Θ_in", "Θin", "in", "params"), []
        )
        out_raw = _pick_field(
            raw, ("outputs", "Theta_out", "theta_out", "Θ_out", "Θout", "out", "return"), []
        )
        act_raw = _pick_field(raw, ("actions", "Pi", "pi", "Π", "action", "code"), "")
    else:
        raise ParseError(
            f"Unsupported GIT entry format for '{iid}': expected dict or 8-tuple"
        )

    guard = _strip_outer_brackets(str(guard_raw or ""))
    if guard in ("-", "∅"):
        guard = ""
    caller = str(caller_raw or "").strip()
    callee = str(callee_raw or "").strip()
    nature = str(nature_raw or "call").strip().lower()
    operation = str(op_raw or "").strip()
    if operation in ("-", "∅"):
        operation = ""
    inputs = _normalize_param_list(in_raw)
    outputs = _normalize_param_list(out_raw)
    actions = str(act_raw or "").strip()
    if actions in ("-", "∅"):
        actions = ""

    if not caller:
        raise ParseError(f"GIT entry '{iid}' is missing required caller (Xi)")
    if not callee:
        raise ParseError(f"GIT entry '{iid}' is missing required callee (Gamma)")
    if nature not in VALID_NATURES:
        raise ParseError(
            f"GIT entry '{iid}' has invalid nature '{nature}'; "
            f"expected one of {sorted(VALID_NATURES)}"
        )

    label = format_interaction_label(guard, operation, inputs, outputs, nature=nature)
    return {
        "id": iid,
        "guard": guard,
        "caller": caller,
        "nature": nature,
        "callee": callee,
        "operation": operation,
        "inputs": inputs,
        "outputs": outputs,
        "actions": actions,
        "label": label,
        "label_length": len(label),
    }


def _parse_markdown_git_table(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    table_lines = [line for line in lines if "|" in line]
    if len(table_lines) < 2:
        raise ParseError("Markdown GIT table must include a header row and data rows")

    def split_row(line: str) -> list[str]:
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [cell.strip() for cell in stripped.split("|")]

    headers = split_row(table_lines[0])
    rows: list[dict[str, str]] = []
    for line in table_lines[1:]:
        cells = split_row(line)
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells if cell):
            continue
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        rows.append(dict(zip(headers, cells)))
    return rows


def load_git_table(source: Any) -> dict[str, dict[str, Any]]:
    """Load and normalize an 8-Field Guarded Interaction Table (GIT).

    Supported inputs:
    - ``None`` -> empty dict
    - ``dict[id, dict | 8-tuple]``
    - ``list[dict]`` (each dict contains an ``id`` / ``i`` / ``interaction`` key)
    - ``Path`` or ``str`` containing JSON, a Markdown table, or CSV
    """
    if source is None:
        return {}

    if isinstance(source, Path):
        source = source.read_text(encoding="utf-8")

    if isinstance(source, str):
        stripped = source.strip()
        if not stripped:
            return {}
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ParseError(f"Invalid JSON in GIT input: {exc}") from exc
            return load_git_table(parsed)
        if "|" in stripped.splitlines()[0]:
            return load_git_table(_parse_markdown_git_table(stripped))
        reader = csv.DictReader(io.StringIO(stripped))
        if not reader.fieldnames:
            raise ParseError("CSV GIT input is missing header columns")
        return load_git_table(list(reader))

    normalized: dict[str, dict[str, Any]] = {}
    if isinstance(source, Mapping):
        if "interactions" in source and isinstance(source["interactions"], (Mapping, list)):
            return load_git_table(source["interactions"])
        for key, value in source.items():
            entry = _normalize_git_entry(str(key), value)
            normalized[entry["id"]] = entry
        return normalized

    if isinstance(source, Sequence) and not isinstance(source, (str, bytes)):
        for idx, item in enumerate(source):
            if not isinstance(item, Mapping):
                raise ParseError(f"GIT list item at index {idx} must be a mapping")
            iid = _pick_field(item, ("id", "i", "interaction", "symbol", "name"), "")
            if not str(iid).strip():
                raise ParseError(f"GIT list item at index {idx} is missing an 'id' field")
            entry = _normalize_git_entry(str(iid), item)
            normalized[entry["id"]] = entry
        return normalized

    raise ParseError(f"Unsupported GIT table input type: {type(source).__name__}")


class _Lexer:
    """Tokenizer for SBC Revised Process Algebra expressions."""

    KEYWORDS = frozenset(
        {
            "strict",
            "seq",
            "alt",
            "par",
            "ref",
            "raise",
            "neg",
            "critical",
            "opt",
            "break",
            "assert",
            "ignore",
            "consider",
            "loop",
            "pseudo",
            "fork",
            "join",
        }
    )

    def __init__(self, source: str) -> None:
        self.source = source
        self.length = len(source)
        self.pos = 0

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while self.pos < self.length:
            ch = self.source[self.pos]
            if ch.isspace():
                self.pos += 1
                continue

            start = self.pos
            if self.source.startswith(">>", self.pos):
                self.pos += 2
                tokens.append(Token("STRICT_OP", ">>", start, self.pos))
                continue
            if ch == ".":
                self.pos += 1
                tokens.append(Token("STRICT_OP", ".", start, self.pos))
                continue
            if ch == "(":
                self.pos += 1
                tokens.append(Token("LPAREN", "(", start, self.pos))
                continue
            if ch == ")":
                self.pos += 1
                tokens.append(Token("RPAREN", ")", start, self.pos))
                continue
            if ch == ":":
                self.pos += 1
                tokens.append(Token("COLON", ":", start, self.pos))
                continue
            if ch == ",":
                self.pos += 1
                tokens.append(Token("COMMA", ",", start, self.pos))
                continue
            if ch == "*":
                self.pos += 1
                tokens.append(Token("STAR", "*", start, self.pos))
                continue
            if ch == "[":
                tokens.append(self._read_bracket_block())
                continue
            if ch in ("◉", "©"):
                self.pos += 1
                tokens.append(Token("TERMINAL", ch, start, self.pos))
                continue
            if ch == "0" and (
                self.pos + 1 >= self.length
                or not (self.source[self.pos + 1].isalnum() or self.source[self.pos + 1] == "_")
            ):
                self.pos += 1
                tokens.append(Token("ZERO", "0", start, self.pos))
                continue
            if ch.isdigit():
                while self.pos < self.length and self.source[self.pos].isdigit():
                    self.pos += 1
                tokens.append(Token("INT", self.source[start : self.pos], start, self.pos))
                continue
            if ch.isalpha() or ch == "_":
                while self.pos < self.length and (
                    self.source[self.pos].isalnum() or self.source[self.pos] == "_"
                ):
                    self.pos += 1
                word = self.source[start : self.pos]
                kind = f"KW_{word.upper()}" if word in self.KEYWORDS else "IDENT"
                tokens.append(Token(kind, word, start, self.pos))
                if kind in ("KW_PSEUDO", "KW_FORK", "KW_JOIN"):
                    look = self.pos
                    while look < self.length and self.source[look].isspace():
                        look += 1
                    if look < self.length and self.source[look] == "(":
                        self.pos = look
                        tokens.append(self._read_paren_raw())
                continue

            raise ParseError(f"Unexpected character {ch!r}", start, self.source)

        tokens.append(Token("EOF", "", self.length, self.length))
        return tokens

    def _read_paren_raw(self) -> Token:
        start = self.pos
        depth = 0
        quote: str | None = None
        while self.pos < self.length:
            ch = self.source[self.pos]
            if quote is not None:
                if ch == quote:
                    quote = None
                self.pos += 1
                continue
            if ch in ("'", '"'):
                quote = ch
                self.pos += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    content = self.source[start + 1 : self.pos - 1].strip()
                    return Token("PAREN_RAW", content, start, self.pos)
            self.pos += 1
        raise ParseError("Unclosed '(' parenthesis", start, self.source)

    def _read_bracket_block(self) -> Token:
        start = self.pos
        depth = 0
        quote: str | None = None
        while self.pos < self.length:
            ch = self.source[self.pos]
            if quote is not None:
                if ch == quote:
                    quote = None
                self.pos += 1
                continue
            if ch in ("'", '"'):
                quote = ch
                self.pos += 1
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    content = self.source[start + 1 : self.pos - 1].strip()
                    return Token("BRACKET", content, start, self.pos)
            self.pos += 1
        raise ParseError("Unclosed '[' bracket", start, self.source)


def _classify_attribute(name: str) -> str:
    if name in SMD_ATTRIBUTES:
        return "smd"
    if name in AD_ATTRIBUTES:
        return "ad"
    if name in CONTROL_ATTRIBUTES:
        return "control"
    return "custom"


def _parse_cross_diagram_attributes(raw_content: str) -> list[dict[str, Any]]:
    """Parse comma-separated attributes inside ``([attribs]: expr)``."""
    items = _split_top_level(raw_content, ",")
    attributes: list[dict[str, Any]] = []
    for item in items:
        raw = item.strip()
        if not raw:
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)", raw)
        if match:
            name = match.group(1)
            args = _split_top_level(match.group(2), ",")
            attr: dict[str, Any] = {
                "name": name,
                "category": _classify_attribute(name),
                "raw": raw,
            }
            if args:
                attr["args"] = args
            attributes.append(attr)
            continue

        match_bracket = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*\[(.*)\]", raw)
        if match_bracket:
            name = match_bracket.group(1)
            args = _split_top_level(match_bracket.group(2), ",")
            attr = {
                "name": name,
                "category": _classify_attribute(name),
                "raw": raw,
            }
            if args:
                attr["args"] = args
            attributes.append(attr)
            continue

        match_eq = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)", raw)
        if match_eq:
            name = match_eq.group(1)
            val = match_eq.group(2).strip()
            attributes.append(
                {
                    "name": name,
                    "category": _classify_attribute(name),
                    "args": [val],
                    "raw": raw,
                }
            )
            continue

        match_word = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw)
        if match_word:
            name = raw
            attributes.append(
                {
                    "name": name,
                    "category": _classify_attribute(name),
                    "raw": raw,
                }
            )
        else:
            attributes.append(
                {
                    "name": raw,
                    "category": "custom",
                    "raw": raw,
                }
            )
    return attributes


class _RecursiveDescentParser:
    """Recursive-descent parser for SBC Revised Process Algebra."""

    CF_PREFIX_TOKEN_KINDS = frozenset(
        {
            "KW_NEG",
            "KW_CRITICAL",
            "KW_OPT",
            "KW_BREAK",
            "KW_ASSERT",
            "KW_IGNORE",
            "KW_CONSIDER",
            "KW_LOOP",
            "KW_STRICT",
            "KW_SEQ",
            "KW_ALT",
            "KW_PAR",
        }
    )

    def __init__(
        self,
        source: str,
        tokens: list[Token],
        interactions: Mapping[str, Mapping[str, Any]],
        strict_git: bool = False,
    ) -> None:
        self.source = source
        self.tokens = tokens
        self.interactions = interactions
        self.strict_git = strict_git
        self.index = 0
        self.warnings: list[dict[str, Any]] = []
        self.swimlane_hints: dict[str, str] = {}

    def _peek(self, offset: int = 0) -> Token:
        idx = self.index + offset
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def _advance(self) -> Token:
        tok = self.tokens[self.index]
        if self.index < len(self.tokens) - 1:
            self.index += 1
        return tok

    def _expect(self, kind: str, description: str | None = None) -> Token:
        tok = self._peek()
        if tok.kind != kind:
            expected = description or kind
            got = tok.value or tok.kind
            raise ParseError(
                f"Expected {expected}, got {got!r}", tok.start, self.source
            )
        return self._advance()

    def parse(self) -> dict[str, Any]:
        if self._peek().kind == "EOF":
            raise ParseError("Process Algebra expression cannot be empty", 0, self.source)
        node = self._parse_alt()
        if self._peek().kind != "EOF":
            tok = self._peek()
            raise ParseError(
                f"Unexpected trailing token {tok.value!r}", tok.start, self.source
            )
        return node

    def _parse_alt(self) -> dict[str, Any]:
        first_guard, first_node = self._parse_guarded_branch()
        if self._peek().kind != "KW_ALT":
            if first_guard is not None:
                return {
                    "type": "combined_fragment",
                    "kind": "opt",
                    "guard": first_guard,
                    "operands": [{"guard": None, "body": first_node}],
                    "span": first_node["span"],
                }
            return first_node

        operands: list[dict[str, Any]] = [{"guard": first_guard, "body": first_node}]
        start = first_node["span"]["start"]
        end = first_node["span"]["end"]
        while self._peek().kind == "KW_ALT":
            self._advance()
            branch_guard, branch_node = self._parse_guarded_branch()
            operands.append({"guard": branch_guard, "body": branch_node})
            end = branch_node["span"]["end"]

        return {
            "type": "combined_fragment",
            "kind": "alt",
            "guard": None,
            "operands": operands,
            "span": {"start": start, "end": end},
        }

    def _parse_guarded_branch(self) -> tuple[str | None, dict[str, Any]]:
        if self._peek().kind == "BRACKET" and self._peek(1).kind != "COLON":
            guard_tok = self._advance()
            body = self._parse_par()
            body_span = body["span"]
            body = dict(body)
            body["span"] = {"start": guard_tok.start, "end": body_span["end"]}
            return guard_tok.value, body
        return None, self._parse_par()

    def _parse_par(self) -> dict[str, Any]:
        first = self._parse_weak()
        if self._peek().kind != "KW_PAR":
            return first

        operands: list[dict[str, Any]] = [{"guard": None, "body": first}]
        start = first["span"]["start"]
        end = first["span"]["end"]
        while self._peek().kind == "KW_PAR":
            self._advance()
            nxt = self._parse_weak()
            operands.append({"guard": None, "body": nxt})
            end = nxt["span"]["end"]

        return {
            "type": "combined_fragment",
            "kind": "par",
            "guard": None,
            "operands": operands,
            "span": {"start": start, "end": end},
        }

    def _parse_weak(self) -> dict[str, Any]:
        first = self._parse_strict()
        if self._peek().kind != "KW_SEQ":
            return first

        children = [first]
        start = first["span"]["start"]
        end = first["span"]["end"]
        while self._peek().kind == "KW_SEQ":
            self._advance()
            nxt = self._parse_strict()
            children.append(nxt)
            end = nxt["span"]["end"]

        return {
            "type": "sequence",
            "mode": "weak",
            "operator": "seq",
            "explicit_frame": False,
            "children": children,
            "span": {"start": start, "end": end},
        }

    def _parse_strict(self) -> dict[str, Any]:
        node = self._parse_primary()
        while self._peek().kind in ("STRICT_OP", "KW_STRICT"):
            op_tok = self._advance()
            op_symbol = op_tok.value
            rhs = self._parse_primary()
            if (
                node["type"] == "sequence"
                and node["mode"] == "strict"
                and node["operator"] == op_symbol
                and not node["explicit_frame"]
            ):
                node["children"].append(rhs)
                node["span"] = {
                    "start": node["span"]["start"],
                    "end": rhs["span"]["end"],
                }
            else:
                node = {
                    "type": "sequence",
                    "mode": "strict",
                    "operator": op_symbol,
                    "explicit_frame": False,
                    "children": [node, rhs],
                    "span": {
                        "start": node["span"]["start"],
                        "end": rhs["span"]["end"],
                    },
                }
        return node

    def _parse_primary(self) -> dict[str, Any]:
        tok = self._peek()

        if tok.kind == "LPAREN":
            return self._parse_parenthesized()

        if tok.kind == "KW_REF":
            self._advance()
            target_tok = self._peek()
            if target_tok.kind not in ("IDENT",) and not target_tok.kind.startswith("KW_"):
                raise ParseError(
                    "Expected module identifier after 'ref'",
                    target_tok.start,
                    self.source,
                )
            self._advance()
            return {
                "type": "ref",
                "target": target_tok.value,
                "span": {"start": tok.start, "end": target_tok.end},
            }

        if tok.kind == "KW_RAISE":
            self._advance()
            event_tok = self._expect("BRACKET", "'[event_name]' after 'raise'")
            if not event_tok.value:
                raise ParseError(
                    "Event name inside 'raise[...]' cannot be empty",
                    event_tok.start,
                    self.source,
                )
            return {
                "type": "raise",
                "event": event_tok.value,
                "span": {"start": tok.start, "end": event_tok.end},
            }

        if tok.kind == "KW_PSEUDO":
            return self._parse_pseudo()

        if tok.kind in ("KW_FORK", "KW_JOIN"):
            return self._parse_standalone_control()

        if tok.kind == "ZERO":
            self._advance()
            return {
                "type": "terminal",
                "kind": "stop",
                "symbol": "0",
                "span": {"start": tok.start, "end": tok.end},
            }

        if tok.kind == "TERMINAL":
            self._advance()
            term_kind = "final" if tok.value == "◉" else "continue"
            return {
                "type": "terminal",
                "kind": term_kind,
                "symbol": tok.value,
                "span": {"start": tok.start, "end": tok.end},
            }

        if tok.kind == "IDENT":
            self._advance()
            if tok.value == "C" and "C" not in self.interactions:
                return {
                    "type": "terminal",
                    "kind": "continue",
                    "symbol": "C",
                    "span": {"start": tok.start, "end": tok.end},
                }
            resolved = tok.value in self.interactions
            if not resolved:
                if self.strict_git:
                    raise ParseError(
                        f"Interaction '{tok.value}' is not defined in the GIT table",
                        tok.start,
                        self.source,
                    )
                self.warnings.append(
                    {
                        "code": "UNRESOLVED_INTERACTION",
                        "message": f"Interaction '{tok.value}' was not found in the GIT table.",
                        "span": {"start": tok.start, "end": tok.end},
                    }
                )
            return {
                "type": "interaction",
                "id": tok.value,
                "resolved": resolved,
                "span": {"start": tok.start, "end": tok.end},
            }

        raise ParseError(
            f"Unexpected token {tok.value or tok.kind!r} where an expression was expected",
            tok.start,
            self.source,
        )

    def _is_cf_header_at_current(self) -> bool:
        """Look ahead past ``CFtype``, optional ``(min, max)``, and optional ``[...]`` for ``:``."""
        first = self._peek()
        if first.kind not in self.CF_PREFIX_TOKEN_KINDS:
            return False

        offset = 1
        if first.kind == "KW_LOOP" and self._peek(offset).kind == "LPAREN":
            depth = 0
            while True:
                t = self._peek(offset)
                if t.kind == "EOF":
                    return False
                if t.kind == "LPAREN":
                    depth += 1
                elif t.kind == "RPAREN":
                    depth -= 1
                    offset += 1
                    if depth == 0:
                        break
                    continue
                offset += 1

        if self._peek(offset).kind == "BRACKET":
            offset += 1

        return self._peek(offset).kind == "COLON"

    def _parse_parenthesized(self) -> dict[str, Any]:
        lparen = self._expect("LPAREN")

        if self._peek().kind == "BRACKET" and self._peek(1).kind == "COLON":
            return self._parse_annotated(lparen)

        if self._is_cf_header_at_current():
            return self._parse_combined_fragment(lparen)

        inner = self._parse_alt()
        rparen = self._expect("RPAREN", "closing ')'")
        inner = dict(inner)
        inner["span"] = {"start": lparen.start, "end": rparen.end}
        return inner

    def _parse_annotated(self, lparen: Token) -> dict[str, Any]:
        bracket_tok = self._expect("BRACKET")
        self._expect("COLON")
        attributes = _parse_cross_diagram_attributes(bracket_tok.value)
        if not attributes:
            raise ParseError(
                "Attribute bracket '[...]:' cannot be empty",
                bracket_tok.start,
                self.source,
            )

        body = self._parse_alt()
        rparen = self._expect("RPAREN", "closing ')'")
        span = {"start": lparen.start, "end": rparen.end}

        degraded_names = [
            attr["name"]
            for attr in attributes
            if attr["category"] in ("smd", "ad", "control")
        ]
        if degraded_names:
            self.warnings.append(
                {
                    "code": "DEGRADED_CROSS_DIAGRAM_ATTRIB",
                    "message": (
                        "Cross-diagram attribute(s) "
                        f"{', '.join(degraded_names)} preserved in annotated AST node "
                        "for graceful sequence diagram rendering."
                    ),
                    "span": span,
                }
            )

        # Record swimlane hint if inlane(Name) is applied around interactions.
        for attr in attributes:
            if attr["name"] == "inlane" and attr.get("args"):
                lane_name = attr["args"][0]
                for iid in _collect_interaction_ids(body):
                    entry = self.interactions.get(iid)
                    if entry:
                        self.swimlane_hints.setdefault(entry["caller"], lane_name)
                        self.swimlane_hints.setdefault(entry["callee"], lane_name)

        return {
            "type": "annotated",
            "attributes": attributes,
            "body": body,
            "span": span,
        }

    def _parse_combined_fragment(self, lparen: Token) -> dict[str, Any]:
        kw_tok = self._advance()
        kind = kw_tok.value

        loop_min: int | None = None
        loop_max: int | str | None = None
        guard: str | None = None
        items: list[str] | None = None

        if kind == "loop" and self._peek().kind == "LPAREN":
            loop_min, loop_max = self._parse_loop_bounds()

        if self._peek().kind == "BRACKET":
            bracket_tok = self._advance()
            if kind in ("ignore", "consider"):
                items = _split_top_level(bracket_tok.value, ",")
                if not items:
                    raise ParseError(
                        f"'{kind}[...]' requires at least one interaction item",
                        bracket_tok.start,
                        self.source,
                    )
            else:
                guard = bracket_tok.value if bracket_tok.value else None

        self._expect("COLON", "':' after combined fragment header")
        body = self._parse_alt()
        rparen = self._expect("RPAREN", "closing ')'")
        span = {"start": lparen.start, "end": rparen.end}

        if kind in FRAMED_SEQUENCE_KINDS:
            mode = "strict" if kind == "strict" else "weak"
            if body["type"] == "sequence" and body["mode"] == mode and not body["explicit_frame"]:
                children = body["children"]
            else:
                children = [body]
            return {
                "type": "sequence",
                "mode": mode,
                "operator": kind,
                "explicit_frame": True,
                "children": children,
                "span": span,
            }

        if kind in ("alt", "par"):
            if body["type"] == "combined_fragment" and body["kind"] == kind:
                result = dict(body)
                result["span"] = span
                if guard is not None:
                    result["guard"] = guard
                return result
            return {
                "type": "combined_fragment",
                "kind": kind,
                "guard": guard,
                "operands": [{"guard": None, "body": body}],
                "span": span,
            }

        node: dict[str, Any] = {
            "type": "combined_fragment",
            "kind": kind,
            "operands": [{"guard": None, "body": body}],
            "span": span,
        }
        if kind == "loop":
            node["min"] = loop_min
            node["max"] = loop_max
            node["guard"] = guard
        elif kind in ("ignore", "consider"):
            node["items"] = items or []
        elif kind in ("opt", "break", "assert"):
            node["guard"] = guard
        elif guard is not None:
            node["guard"] = guard
        return node

    def _parse_loop_bounds(self) -> tuple[int | None, int | str | None]:
        self._expect("LPAREN")
        first_tok = self._peek()
        if first_tok.kind == "RPAREN":
            self._advance()
            return None, None

        loop_min = self._parse_non_negative_int()
        if self._peek().kind == "COMMA":
            self._advance()
            if self._peek().kind == "STAR":
                self._advance()
                loop_max: int | str | None = "*"
            else:
                loop_max = self._parse_non_negative_int()
        else:
            loop_max = loop_min

        self._expect("RPAREN", "closing ')' for loop bounds")
        if isinstance(loop_max, int) and loop_min is not None and loop_max < loop_min:
            raise ParseError(
                f"loop max ({loop_max}) cannot be smaller than min ({loop_min})",
                first_tok.start,
                self.source,
            )
        return loop_min, loop_max

    def _parse_non_negative_int(self) -> int:
        tok = self._peek()
        if tok.kind == "ZERO":
            self._advance()
            return 0
        if tok.kind == "INT":
            self._advance()
            return int(tok.value)
        raise ParseError(
            f"Expected non-negative integer in loop bounds, got {tok.value or tok.kind!r}",
            tok.start,
            self.source,
        )

    def _parse_pseudo(self) -> dict[str, Any]:
        kw_tok = self._expect("KW_PSEUDO")
        paren_tok = self._expect("PAREN_RAW", "'(...)' after 'pseudo'")
        parts = _split_top_level(paren_tok.value, ",")
        if not parts:
            raise ParseError("pseudo(...) cannot be empty", paren_tok.start, self.source)
        kind = parts[0]
        args = parts[1:]
        raw = self.source[kw_tok.start : paren_tok.end]
        span = {"start": kw_tok.start, "end": paren_tok.end}
        self.warnings.append(
            {
                "code": "DEGRADED_CROSS_DIAGRAM_ATTRIB",
                "message": f"Cross-diagram construct '{raw}' preserved as pseudo node.",
                "span": span,
            }
        )
        node: dict[str, Any] = {
            "type": "pseudo",
            "kind": kind,
            "raw": raw,
            "span": span,
        }
        if args:
            node["args"] = args
        return node

    def _parse_standalone_control(self) -> dict[str, Any]:
        kw_tok = self._advance()
        args: list[str] = []
        end_pos = kw_tok.end
        if self._peek().kind == "PAREN_RAW":
            paren_tok = self._advance()
            args = _split_top_level(paren_tok.value, ",")
            end_pos = paren_tok.end
        raw = self.source[kw_tok.start : end_pos]
        span = {"start": kw_tok.start, "end": end_pos}
        self.warnings.append(
            {
                "code": "DEGRADED_CROSS_DIAGRAM_ATTRIB",
                "message": f"Cross-diagram control construct '{raw}' preserved as pseudo node.",
                "span": span,
            }
        )
        node: dict[str, Any] = {
            "type": "pseudo",
            "kind": kw_tok.value,
            "raw": raw,
            "span": span,
        }
        if args:
            node["args"] = args
        return node


def _collect_interaction_ids(node: Mapping[str, Any]) -> list[str]:
    """Collect interaction IDs in deterministic pre-order AST traversal."""
    ids: list[str] = []
    node_type = node["type"]
    if node_type == "interaction":
        ids.append(node["id"])
    elif node_type == "sequence":
        for child in node["children"]:
            ids.extend(_collect_interaction_ids(child))
    elif node_type == "combined_fragment":
        for operand in node["operands"]:
            ids.extend(_collect_interaction_ids(operand["body"]))
    elif node_type == "annotated":
        ids.extend(_collect_interaction_ids(node["body"]))
    return ids


def order_lifelines(
    ast: Mapping[str, Any],
    interactions: Mapping[str, Mapping[str, Any]],
    lifeline_roles: Mapping[str, str] | None = None,
    swimlane_hints: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Order lifelines left-to-right based on caller -> callee flow to reduce crossings."""
    referenced_ids = _collect_interaction_ids(ast)
    first_seen: dict[str, int] = {}
    outgoing: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    incoming_count: dict[str, int] = defaultdict(int)
    seen_counter = 0

    def register_participant(pid: str) -> None:
        nonlocal seen_counter
        if pid not in first_seen:
            first_seen[pid] = seen_counter
            seen_counter += 1

    # Traverse AST-referenced interactions first, then any remaining GIT entries.
    ordered_entries: list[Mapping[str, Any]] = []
    for iid in referenced_ids:
        if iid in interactions:
            ordered_entries.append(interactions[iid])
    referenced_set = set(referenced_ids)
    for iid, entry in interactions.items():
        if iid not in referenced_set:
            ordered_entries.append(entry)

    for entry in ordered_entries:
        caller = entry["caller"]
        callee = entry["callee"]
        nature = entry["nature"]
        if nature == "return":
            # A return flows back from callee-of-original-call to original caller.
            register_participant(callee)
            register_participant(caller)
            if callee != caller:
                outgoing[callee][caller] += 1
                incoming_count[caller] += 1
        else:
            register_participant(caller)
            register_participant(callee)
            if caller != callee:
                outgoing[caller][callee] += 1
                incoming_count[callee] += 1

    all_ids = list(first_seen.keys())
    if not all_ids:
        return []

    # Start from root callers (lowest incoming call count, then earliest first_seen),
    # expanding along strongest outgoing call edges (BFS/flow order).
    placed: list[str] = []
    placed_set: set[str] = set()
    remaining = set(all_ids)

    while remaining:
        roots = sorted(
            remaining,
            key=lambda pid: (incoming_count[pid], first_seen[pid]),
        )
        queue: deque[str] = deque([roots[0]])
        while queue:
            current = queue.popleft()
            if current in placed_set:
                continue
            placed.append(current)
            placed_set.add(current)
            remaining.discard(current)

            neighbors = [
                nbr for nbr in outgoing[current].keys() if nbr in remaining
            ]
            neighbors.sort(
                key=lambda nbr: (-outgoing[current][nbr], first_seen[nbr])
            )
            queue.extend(neighbors)

    roles = lifeline_roles or {}
    lanes = swimlane_hints or {}
    lifelines: list[dict[str, Any]] = []
    for idx, pid in enumerate(placed):
        role = roles.get(pid, "participant")
        if role not in VALID_LIFELINE_ROLES:
            role = "participant"
        item: dict[str, Any] = {
            "id": pid,
            "name": pid,
            "order": idx,
            "role": role,
        }
        if pid in lanes:
            item["swimlane"] = lanes[pid]
        lifelines.append(item)
    return lifelines


def compute_layout_hints(
    ast: Mapping[str, Any],
    interactions: Mapping[str, Mapping[str, Any]],
    lifelines: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute anti-overlap spacing hints and sequencing/nesting metrics for renderer.py."""
    order_map = {ll["id"]: ll["order"] for ll in lifelines}
    pair_max: dict[tuple[str, str], int] = {}
    max_label_length = 0
    has_weak = False
    has_strict = False
    max_depth = 0

    def walk(node: Mapping[str, Any], depth: int) -> None:
        nonlocal max_label_length, has_weak, has_strict, max_depth
        node_type = node["type"]
        if node_type == "interaction":
            entry = interactions.get(node["id"])
            if entry is not None:
                lbl_len = int(entry.get("label_length", len(entry["label"])))
                if lbl_len > max_label_length:
                    max_label_length = lbl_len
                u = entry["caller"]
                v = entry["callee"]
                if order_map.get(u, 0) <= order_map.get(v, 0):
                    key = (u, v)
                else:
                    key = (v, u)
                pair_max[key] = max(pair_max.get(key, 0), lbl_len)
        elif node_type == "sequence":
            if node["mode"] == "weak":
                has_weak = True
            else:
                has_strict = True
            next_depth = depth + 1 if node.get("explicit_frame") else depth
            if next_depth > max_depth:
                max_depth = next_depth
            for child in node["children"]:
                walk(child, next_depth)
        elif node_type == "combined_fragment":
            next_depth = depth + 1
            if next_depth > max_depth:
                max_depth = next_depth
            for operand in node["operands"]:
                walk(operand["body"], next_depth)
        elif node_type == "annotated":
            walk(node["body"], depth)

    walk(ast, 0)

    pair_spacings = [
        {"from": u, "to": v, "max_label_length": length}
        for (u, v), length in sorted(
            pair_max.items(),
            key=lambda kv: (order_map.get(kv[0][0], 0), order_map.get(kv[0][1], 0)),
        )
    ]

    return {
        "max_label_length": max_label_length,
        "pair_spacings": pair_spacings,
        "has_weak_sequencing": has_weak,
        "has_strict_sequencing": has_strict,
        "max_fragment_depth": max_depth,
    }


def parse_process_algebra(
    expression: str,
    git_table: Any = None,
    *,
    title: str | None = None,
    lifeline_roles: Mapping[str, str] | None = None,
    strict_git: bool = False,
) -> dict[str, Any]:
    """Parse a Revised Process Algebra expression + GIT table into schema.json v1.0 JSON."""
    if not isinstance(expression, str):
        raise ParseError("Process Algebra expression must be a string")

    interactions = load_git_table(git_table)
    tokens = _Lexer(expression).tokenize()
    parser = _RecursiveDescentParser(
        source=expression,
        tokens=tokens,
        interactions=interactions,
        strict_git=strict_git,
    )
    ast = parser.parse()
    lifelines = order_lifelines(
        ast,
        interactions,
        lifeline_roles=lifeline_roles,
        swimlane_hints=parser.swimlane_hints,
    )
    layout_hints = compute_layout_hints(ast, interactions, lifelines)

    metadata: dict[str, Any] = {
        "source_expression": expression,
        "warnings": parser.warnings,
    }
    if title is not None:
        metadata["title"] = title

    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata,
        "lifelines": lifelines,
        "interactions": interactions,
        "ast": ast,
        "layout_hints": layout_hints,
    }


def _build_cli() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        description="Parse Revised Process Algebra + 8-Field GIT into AST JSON (schema.json v1.0)."
    )
    expr_group = cli.add_mutually_exclusive_group(required=True)
    expr_group.add_argument("--expr", help="Process Algebra expression string")
    expr_group.add_argument("--expr-file", type=Path, help="Path to file containing expression")
    cli.add_argument(
        "--git",
        type=Path,
        default=None,
        help="Path to GIT table file (JSON, Markdown table, or CSV)",
    )
    cli.add_argument("--title", default=None, help="Optional diagram title")
    cli.add_argument(
        "--strict-git",
        action="store_true",
        help="Fail with an error if any interaction ID is missing from the GIT table",
    )
    cli.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write resulting JSON to file instead of stdout",
    )
    return cli


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_cli().parse_args(argv)
    expression = (
        args.expr
        if args.expr is not None
        else args.expr_file.read_text(encoding="utf-8").strip()
    )
    result = parse_process_algebra(
        expression,
        args.git,
        title=args.title,
        strict_git=args.strict_git,
    )
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    sys.exit(main())
