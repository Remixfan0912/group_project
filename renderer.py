"""Render the intermediate AST and lifelines JSON v1.0 as a UML sequence diagram.

Use render_plantuml(document) from Python, or run python renderer.py --help.
"""

import argparse
import json
from pathlib import Path
import subprocess
import textwrap


_THEME_PATH = Path(__file__).with_name("theme.puml")
_ROLES = {"participant", "actor", "boundary", "control", "entity", "database"}
_NATIVE_FRAGMENTS = {"alt", "par", "opt", "loop", "break", "critical"}
_GROUP_FRAGMENTS = {"neg", "assert", "ignore", "consider"}
_LABEL_WIDTH = 54
_TEXT_ESCAPES = str.maketrans({
    character: f"<U+{ord(character):04X}>" for character in '"<>\\[]#%!*_/~&{}'
})


def _literal(text, *, wrap=False):
    """Keep JSON text literal inside PlantUML commands and Creole labels."""
    lines = str(text).splitlines() or [""]
    if wrap:
        lines = [
            part
            for line in lines
            for part in (textwrap.wrap(line, _LABEL_WIDTH) or [""])
        ]
    return r"\n".join(line.translate(_TEXT_ESCAPES) for line in lines)


def _guard(value):
    return f"[{_literal(value)}]" if value else ""


def _description(node):
    raw = node.get("raw")
    if raw:
        return raw
    name = node.get("name") or node["kind"]
    args = node.get("args", [])
    return f"{name}({', '.join(args)})" if args else name


class _SequenceDiagram:
    def __init__(self, document):
        self.interactions = document["interactions"]
        self.lines = ["@startuml", _THEME_PATH.read_text(encoding="utf-8").rstrip()]
        lifelines = sorted(document["lifelines"], key=lambda item: item["order"])
        self.aliases = {item["id"]: f"L{index}" for index, item in enumerate(lifelines)}
        if len(self.aliases) != len(lifelines):
            raise ValueError("Lifeline IDs must be unique")

        # PlantUML fits each arrow to its rendered label. Bound the extra padding
        # so a single long label does not spread out the entire diagram.
        hints = document.get("layout_hints", {})
        longest = max(
            [hints.get("max_label_length", 0)]
            + [pair["max_label_length"] for pair in hints.get("pair_spacings", [])]
            + [len(entry["label"]) for entry in self.interactions.values()]
        )
        padding = 18 + min(longest, _LABEL_WIDTH) // 3
        self.lines.extend(["<style>", f"participant {{\n    Padding {padding}\n}}", "</style>"])
        title = document["metadata"].get("title")
        if title:
            self.lines.append(f"title {_literal(title, wrap=True)}")
        for item in lifelines:
            role = item.get("role", "participant")
            if role not in _ROLES:
                raise ValueError(f"Unsupported lifeline role: {role}")
            name = _literal(item["name"], wrap=True)
            self.lines.append(f'{role} "{name}" as {self.aliases[item["id"]]}')

        anchors = list(self.aliases.values())
        if not anchors:
            self.lines.append('participant "Process" as Process')
            anchors = ["Process"]
        self.span = ", ".join(dict.fromkeys([anchors[0], anchors[-1]]))

    def note(self, content, *, span=None):
        self.lines.append(f"note over {span or self.span} : {_literal(content, wrap=True)}")

    def interaction(self, node, calls):
        interaction_id = node["id"]
        if not node["resolved"]:
            self.note(f"Unresolved interaction: {interaction_id}")
            return
        if interaction_id not in self.interactions:
            raise ValueError(f"Resolved interaction {interaction_id!r} has no GIT entry")
        entry = self.interactions[interaction_id]
        try:
            caller = self.aliases[entry["caller"]]
            callee = self.aliases[entry["callee"]]
        except KeyError as error:
            raise ValueError(
                f"Interaction {interaction_id!r} references unknown lifeline {error.args[0]!r}"
            ) from error

        nature = entry["nature"]
        label = entry["label"]
        outputs = ", ".join(entry["outputs"])
        if nature == "combined" and outputs:
            label = label.removesuffix(f": {outputs}")
        label = _literal(label, wrap=True)
        if nature == "return":
            self.lines.append(f"{caller} --> {callee} : {label}")
            pending = calls.get(caller)
            if pending and pending[-1][0] == callee:
                pending.pop()
                self.lines.append(f"deactivate {caller}")
        elif nature in {"call", "combined"}:
            self.lines.extend([f"{caller} -> {callee} : {label}", f"activate {callee}"])
            if nature == "call":
                calls.setdefault(callee, []).append((caller, len(self.lines)))
        else:
            raise ValueError(f"Unsupported interaction nature: {nature}")

        if entry["actions"]:
            action = f"Action: {entry['actions']}"
            self.note(action, span=caller if nature == "return" else callee)
        if nature == "combined":
            response = _literal(outputs or "return", wrap=True)
            self.lines.extend([f"{callee} --> {caller} : {response}", f"deactivate {callee}"])

    def fragment(self, node, calls):
        kind = node["kind"]
        if kind not in _NATIVE_FRAGMENTS | _GROUP_FRAGMENTS:
            raise ValueError(f"Unsupported combined fragment: {kind}")
        operands = node["operands"]
        if not operands:
            raise ValueError(f"Fragment {kind!r} needs an operand")
        keyword = kind if kind in _NATIVE_FRAGMENTS else f"group {kind}"
        heading = []
        if kind == "loop":
            minimum, maximum = node.get("min"), node.get("max")
            if minimum is not None or maximum is not None:
                lower = minimum if minimum is not None else "?"
                upper = maximum if maximum is not None else "?"
                heading.append(f"({lower}, {upper})")
        if kind in {"ignore", "consider"} and node.get("items"):
            heading.append(f"({_literal(', '.join(node['items']))})")

        for index, operand in enumerate(operands):
            labels = list(heading) if index == 0 else []
            # Native PlantUML fragment headers supply their own outer brackets.
            guards = [node.get("guard")] if index == 0 else []
            guards.append(operand.get("guard"))
            for guard in dict.fromkeys(filter(None, guards)):
                labels.append(_literal(guard) if not labels else _guard(guard))
            if operand.get("label"):
                labels.append(_literal(operand["label"]))
            prefix = keyword if index == 0 else "else"
            if labels and index == 0 and kind in _GROUP_FRAGMENTS:
                self.lines.append(f"{prefix} [{' '.join(labels)}]")
            else:
                self.lines.append(" ".join([prefix, *labels]))
            # Competing operands must not close calls opened by other paths.
            # A single displayed path can return from an enclosing call.
            local_calls = calls if len(operands) == 1 and kind != "neg" else {}
            incoming = {call for pending in local_calls.values() for call in pending}
            self.node(operand["body"], local_calls)
            for receiver, pending in local_calls.items():
                while pending and pending[-1] not in incoming:
                    pending.pop()
                    self.lines.append(f"deactivate {receiver}")
        self.lines.append("end")

    def node(self, node, calls):
        match node["type"]:
            case "interaction":
                self.interaction(node, calls)
            case "sequence":
                framed = node["explicit_frame"] or node["mode"] == "weak"
                if framed:
                    self.lines.append("group seq" if node["mode"] == "weak" else "group strict")
                for index, child in enumerate(node["children"]):
                    if framed and index:
                        self.lines.append("else")
                    self.node(child, calls)
                if framed:
                    self.lines.append("end")
            case "combined_fragment":
                self.fragment(node, calls)
            case "ref":
                self.lines.append(f"ref over {self.span} : {_literal(node['target'], wrap=True)}")
            case "raise":
                self.note(f"raise[{node['event']}]")
            case "terminal":
                self.note(f"{node['kind']} {node['symbol']}")
            case "annotated":
                self.note(", ".join(_description(attribute) for attribute in node["attributes"]))
                self.node(node["body"], calls)
            case "pseudo":
                self.note(_description(node))
            case _:
                raise ValueError(f"Unsupported AST node type: {node['type']}")


def render_plantuml(document):
    """Return self-contained PlantUML from a parsed schema v1.0 document."""
    if document.get("schema_version") != "1.0":
        raise ValueError("Expected schema_version '1.0'")
    diagram = _SequenceDiagram(document)
    diagram.node(document["ast"], {})
    return "\n".join([*diagram.lines, "@enduml", ""])


def _export(source, jar, image_format):
    options = ["-Sdpi=144"] if image_format == "png" else []
    result = subprocess.run(
        ["java", "-Djava.awt.headless=true", "-DPLANTUML_SECURITY_PROFILE=SANDBOX",
         "-jar", str(jar), "-charset", "UTF-8", "-pipe", f"-t{image_format}", *options],
        input=source.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if result.returncode or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"PlantUML {image_format.upper()} export failed: {detail or result.returncode}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Intermediate AST and lifelines JSON file")
    parser.add_argument("-o", "--output", type=Path, help="PlantUML file (default: input with .puml suffix)")
    parser.add_argument("--plantuml-jar", type=Path, help="Also export SVG and PNG using this local JAR")
    args = parser.parse_args()
    output = args.output or args.input.with_suffix(".puml")
    if output.suffix.lower() != ".puml":
        parser.error("--output must end in .puml")
    paths = [output]
    if args.plantuml_jar:
        paths.extend([output.with_suffix(".svg"), output.with_suffix(".png")])
    if args.input.resolve() in [path.resolve() for path in paths]:
        parser.error("Output must not overwrite the input document")
    try:
        document = json.loads(args.input.read_text(encoding="utf-8-sig"))
        source = render_plantuml(document)
        contents = [source.encode("utf-8")]
        if args.plantuml_jar:
            contents.extend(_export(source, args.plantuml_jar, kind) for kind in ("svg", "png"))
        for path, data in zip(paths, contents):
            path.write_bytes(data)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(1, f"renderer: {error}\n")


if __name__ == "__main__":
    main()
