import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "schema.json"


def _collect_refs(node: object) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            refs.append(node["$ref"])
        for value in node.values():
            refs.extend(_collect_refs(value))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_collect_refs(item))
    return refs


def _validate_ast_node(node: dict, defs: dict, interactions: dict) -> None:
    node_type = node.get("type")
    type_to_def = {
        "interaction": "InteractionNode",
        "sequence": "SequenceNode",
        "combined_fragment": "CombinedFragmentNode",
        "ref": "RefNode",
        "raise": "RaiseNode",
        "terminal": "TerminalNode",
        "annotated": "AnnotatedNode",
        "pseudo": "PseudoNode",
    }
    if node_type not in type_to_def:
        raise AssertionError(f"Unknown AST node type: {node_type!r}")

    schema_def = defs[type_to_def[node_type]]
    allowed = set(schema_def["properties"].keys())
    required = set(schema_def["required"])
    actual = set(node.keys())
    if not required.issubset(actual):
        raise AssertionError(f"{node_type} missing required keys: {required - actual}")
    if not actual.issubset(allowed):
        raise AssertionError(f"{node_type} has unexpected keys: {actual - allowed}")

    if node_type == "interaction":
        if node["resolved"] and node["id"] not in interactions:
            raise AssertionError(f"Resolved interaction {node['id']!r} missing from interactions map")
    elif node_type == "sequence":
        assert node["mode"] in schema_def["properties"]["mode"]["enum"]
        assert node["operator"] in schema_def["properties"]["operator"]["enum"]
        assert isinstance(node["children"], list) and len(node["children"]) >= 1
        for child in node["children"]:
            _validate_ast_node(child, defs, interactions)
    elif node_type == "combined_fragment":
        assert node["kind"] in schema_def["properties"]["kind"]["enum"]
        assert isinstance(node["operands"], list) and len(node["operands"]) >= 1
        for operand in node["operands"]:
            assert "body" in operand
            _validate_ast_node(operand["body"], defs, interactions)
    elif node_type == "annotated":
        assert isinstance(node["attributes"], list) and len(node["attributes"]) >= 1
        _validate_ast_node(node["body"], defs, interactions)


class SchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_schema_file_and_draft_metadata(self) -> None:
        self.assertEqual(
            self.schema["$schema"],
            "https://json-schema.org/draft/2020-12/schema",
        )
        self.assertEqual(self.schema["type"], "object")
        self.assertEqual(
            set(self.schema["required"]),
            {"schema_version", "metadata", "lifelines", "interactions", "ast"},
        )

    def test_all_internal_refs_resolve(self) -> None:
        defs = self.schema["$defs"]
        for ref in _collect_refs(self.schema):
            self.assertTrue(ref.startswith("#/$defs/"), f"Unexpected ref format: {ref}")
            target = ref.removeprefix("#/$defs/")
            self.assertIn(target, defs, f"Dangling $ref target: {ref}")

    def test_covers_all_required_grammar_constructs(self) -> None:
        defs = self.schema["$defs"]

        seq_ops = set(defs["SequenceNode"]["properties"]["operator"]["enum"])
        self.assertEqual(seq_ops, {">>", ".", "strict", "seq"})

        cf_kinds = set(defs["CombinedFragmentNode"]["properties"]["kind"]["enum"])
        self.assertEqual(
            cf_kinds,
            {"alt", "par", "opt", "loop", "break", "neg", "critical", "assert", "ignore", "consider"},
        )

        terminals = set(defs["TerminalNode"]["properties"]["symbol"]["enum"])
        self.assertEqual(terminals, {"0", "◉", "C", "©"})

        git_required = set(defs["GitInteraction"]["required"])
        self.assertTrue(
            {"id", "guard", "caller", "nature", "callee", "operation", "inputs", "outputs", "actions", "label"}.issubset(
                git_required
            )
        )
        self.assertEqual(
            set(defs["GitInteraction"]["properties"]["nature"]["enum"]),
            {"call", "return", "combined"},
        )

    def test_embedded_examples_match_contract(self) -> None:
        examples = self.schema.get("examples", [])
        self.assertGreaterEqual(len(examples), 1)
        defs = self.schema["$defs"]
        required_top = set(self.schema["required"])
        allowed_top = set(self.schema["properties"].keys())

        for example in examples:
            keys = set(example.keys())
            self.assertTrue(required_top.issubset(keys))
            self.assertTrue(keys.issubset(allowed_top))
            self.assertEqual(example["schema_version"], "1.0")

            lifeline_ids = {ll["id"] for ll in example["lifelines"]}
            for idx, ll in enumerate(example["lifelines"]):
                self.assertEqual(ll["order"], idx)

            for interaction_id, entry in example["interactions"].items():
                self.assertEqual(entry["id"], interaction_id)
                self.assertIn(entry["caller"], lifeline_ids)
                self.assertIn(entry["callee"], lifeline_ids)
                if "label_length" in entry:
                    self.assertEqual(entry["label_length"], len(entry["label"]))

            _validate_ast_node(example["ast"], defs, example["interactions"])


if __name__ == "__main__":
    unittest.main()
