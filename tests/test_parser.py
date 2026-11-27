import json
from pathlib import Path
import tempfile
import unittest

import parser as pa_parser
from parser import ParseError, load_git_table, parse_process_algebra


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((PROJECT_ROOT / "schema.json").read_text(encoding="utf-8"))


def assert_matches_schema(case: unittest.TestCase, doc: dict) -> None:
    """Validate a parser output document against schema.json v1.0 using stdlib only."""
    defs = SCHEMA["$defs"]
    required_top = set(SCHEMA["required"])
    allowed_top = set(SCHEMA["properties"].keys())
    case.assertTrue(required_top.issubset(doc.keys()), f"Missing top keys: {required_top - doc.keys()}")
    case.assertTrue(set(doc.keys()).issubset(allowed_top), f"Extra top keys: {set(doc.keys()) - allowed_top}")
    case.assertEqual(doc["schema_version"], "1.0")

    # Metadata
    meta = doc["metadata"]
    case.assertTrue(set(defs["Metadata"]["required"]).issubset(meta.keys()))
    case.assertTrue(set(meta.keys()).issubset(defs["Metadata"]["properties"].keys()))
    for diag in meta["warnings"]:
        case.assertTrue(set(defs["Diagnostic"]["required"]).issubset(diag.keys()))
        case.assertTrue(set(diag.keys()).issubset(defs["Diagnostic"]["properties"].keys()))

    # Lifelines
    lifeline_ids = set()
    for idx, ll in enumerate(doc["lifelines"]):
        case.assertTrue(set(defs["Lifeline"]["required"]).issubset(ll.keys()))
        case.assertTrue(set(ll.keys()).issubset(defs["Lifeline"]["properties"].keys()))
        case.assertEqual(ll["order"], idx)
        lifeline_ids.add(ll["id"])

    # Interactions
    for iid, entry in doc["interactions"].items():
        case.assertEqual(entry["id"], iid)
        case.assertTrue(set(defs["GitInteraction"]["required"]).issubset(entry.keys()))
        case.assertTrue(set(entry.keys()).issubset(defs["GitInteraction"]["properties"].keys()))
        case.assertIn(entry["nature"], defs["GitInteraction"]["properties"]["nature"]["enum"])
        case.assertIn(entry["caller"], lifeline_ids)
        case.assertIn(entry["callee"], lifeline_ids)
        case.assertEqual(entry["label_length"], len(entry["label"]))

    # Layout hints
    if "layout_hints" in doc:
        hints = doc["layout_hints"]
        case.assertTrue(set(hints.keys()).issubset(defs["LayoutHints"]["properties"].keys()))
        for pair in hints.get("pair_spacings", []):
            case.assertEqual(set(pair.keys()), {"from", "to", "max_label_length"})

    # Recursive AST check
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

    def check_node(node: dict) -> None:
        node_type = node["type"]
        case.assertIn(node_type, type_to_def)
        schema_def = defs[type_to_def[node_type]]
        case.assertTrue(set(schema_def["required"]).issubset(node.keys()))
        case.assertTrue(set(node.keys()).issubset(schema_def["properties"].keys()))
        if "span" in node:
            case.assertEqual(set(node["span"].keys()), {"start", "end"})
            case.assertGreaterEqual(node["span"]["end"], node["span"]["start"])

        if node_type == "interaction":
            if node["resolved"]:
                case.assertIn(node["id"], doc["interactions"])
        elif node_type == "sequence":
            case.assertIn(node["mode"], schema_def["properties"]["mode"]["enum"])
            case.assertIn(node["operator"], schema_def["properties"]["operator"]["enum"])
            case.assertIsInstance(node["explicit_frame"], bool)
            case.assertGreaterEqual(len(node["children"]), 1)
            for child in node["children"]:
                check_node(child)
        elif node_type == "combined_fragment":
            case.assertIn(node["kind"], schema_def["properties"]["kind"]["enum"])
            case.assertGreaterEqual(len(node["operands"]), 1)
            if "items" in node:
                case.assertIsInstance(node["items"], list)
            for operand in node["operands"]:
                case.assertTrue(set(operand.keys()).issubset(defs["FragmentOperand"]["properties"].keys()))
                check_node(operand["body"])
        elif node_type == "terminal":
            case.assertIn(node["kind"], schema_def["properties"]["kind"]["enum"])
            case.assertIn(node["symbol"], schema_def["properties"]["symbol"]["enum"])
        elif node_type == "annotated":
            case.assertGreaterEqual(len(node["attributes"]), 1)
            for attr in node["attributes"]:
                case.assertTrue(set(defs["CrossDiagramAttribute"]["required"]).issubset(attr.keys()))
                case.assertTrue(set(attr.keys()).issubset(defs["CrossDiagramAttribute"]["properties"].keys()))
                case.assertIn(attr["category"], defs["CrossDiagramAttribute"]["properties"]["category"]["enum"])
            check_node(node["body"])

    check_node(doc["ast"])


SAMPLE_GIT = {
    "i1": ("", "Client", "call", "AuthService", "login", ["user", "pwd"], [], ""),
    "i2": ("", "AuthService", "call", "UserDB", "verify", ["user"], ["ok"], ""),
    "i3": ("ok", "AuthService", "return", "Client", "issueToken", [], ["token"], "logSuccess()"),
    "i4": ("", "Client", "combined", "AuditLog", "record", ["event"], [], ""),
}


class ProcessAlgebraParserTests(unittest.TestCase):
    def test_strict_and_weak_sequencing_and_precedence(self) -> None:
        doc = parse_process_algebra("i1 >> i2 seq i3 par i4 alt ref Fallback", SAMPLE_GIT)
        assert_matches_schema(self, doc)

        ast = doc["ast"]
        self.assertEqual(ast["type"], "combined_fragment")
        self.assertEqual(ast["kind"], "alt")
        self.assertEqual(len(ast["operands"]), 2)
        self.assertEqual(ast["operands"][1]["body"]["type"], "ref")
        self.assertEqual(ast["operands"][1]["body"]["target"], "Fallback")

        par_node = ast["operands"][0]["body"]
        self.assertEqual(par_node["kind"], "par")
        self.assertEqual(len(par_node["operands"]), 2)
        self.assertEqual(par_node["operands"][1]["body"]["id"], "i4")

        weak_node = par_node["operands"][0]["body"]
        self.assertEqual(weak_node["type"], "sequence")
        self.assertEqual(weak_node["mode"], "weak")
        self.assertEqual(weak_node["operator"], "seq")
        self.assertFalse(weak_node["explicit_frame"])

        strict_node = weak_node["children"][0]
        self.assertEqual(strict_node["type"], "sequence")
        self.assertEqual(strict_node["mode"], "strict")
        self.assertEqual(strict_node["operator"], ">>")
        self.assertEqual([c["id"] for c in strict_node["children"]], ["i1", "i2"])

        self.assertTrue(doc["layout_hints"]["has_strict_sequencing"])
        self.assertTrue(doc["layout_hints"]["has_weak_sequencing"])

    def test_dot_and_keyword_strict_and_explicit_frames(self) -> None:
        doc = parse_process_algebra("(strict: i1.i2 strict i3) >> (seq: i3 seq i4)", SAMPLE_GIT)
        assert_matches_schema(self, doc)

        outer = doc["ast"]
        self.assertEqual(outer["type"], "sequence")
        self.assertEqual(outer["mode"], "strict")
        self.assertEqual(len(outer["children"]), 2)

        strict_frame = outer["children"][0]
        self.assertEqual(strict_frame["mode"], "strict")
        self.assertEqual(strict_frame["operator"], "strict")
        self.assertTrue(strict_frame["explicit_frame"])

        seq_frame = outer["children"][1]
        self.assertEqual(seq_frame["mode"], "weak")
        self.assertEqual(seq_frame["operator"], "seq")
        self.assertTrue(seq_frame["explicit_frame"])
        self.assertEqual([c["id"] for c in seq_frame["children"]], ["i3", "i4"])

    def test_all_combined_fragments(self) -> None:
        expr = (
            "(neg: i1) >> "
            "(critical: i1 >> i2) >> "
            "(opt[valid]: i3) >> "
            "(break[failed]: raise[Abort]) >> "
            "(assert[ok == 1]: i2) >> "
            "(ignore[i3, i4]: i1 seq i2) >> "
            "(consider[i1, i2]: i1 >> i2) >> "
            "(loop(1, 3)[retry]: i1) >> "
            "(loop(0, *)[more]: i2) >> "
            "(loop(2): i3) >> "
            "(loop[cond]: i4)"
        )
        doc = parse_process_algebra(expr, SAMPLE_GIT)
        assert_matches_schema(self, doc)

        children = doc["ast"]["children"]
        self.assertEqual(len(children), 11)
        self.assertEqual(children[0]["kind"], "neg")
        self.assertEqual(children[1]["kind"], "critical")
        self.assertEqual((children[2]["kind"], children[2]["guard"]), ("opt", "valid"))
        self.assertEqual((children[3]["kind"], children[3]["guard"]), ("break", "failed"))
        self.assertEqual(children[3]["operands"][0]["body"]["type"], "raise")
        self.assertEqual(children[3]["operands"][0]["body"]["event"], "Abort")
        self.assertEqual((children[4]["kind"], children[4]["guard"]), ("assert", "ok == 1"))
        self.assertEqual((children[5]["kind"], children[5]["items"]), ("ignore", ["i3", "i4"]))
        self.assertEqual((children[6]["kind"], children[6]["items"]), ("consider", ["i1", "i2"]))
        self.assertEqual((children[7]["min"], children[7]["max"], children[7]["guard"]), (1, 3, "retry"))
        self.assertEqual((children[8]["min"], children[8]["max"], children[8]["guard"]), (0, "*", "more"))
        self.assertEqual((children[9]["min"], children[9]["max"], children[9]["guard"]), (2, 2, None))
        self.assertEqual((children[10]["min"], children[10]["max"], children[10]["guard"]), (None, None, "cond"))

    def test_guarded_alt_branches(self) -> None:
        doc = parse_process_algebra("[x > 0] i1 alt [x <= 0] i4", SAMPLE_GIT)
        assert_matches_schema(self, doc)

        ast = doc["ast"]
        self.assertEqual(ast["kind"], "alt")
        self.assertEqual(ast["operands"][0]["guard"], "x > 0")
        self.assertEqual(ast["operands"][0]["body"]["id"], "i1")
        self.assertEqual(ast["operands"][1]["guard"], "x <= 0")
        self.assertEqual(ast["operands"][1]["body"]["id"], "i4")

    def test_terminals_and_identifier_edge_cases(self) -> None:
        doc = parse_process_algebra("0 alt ◉ alt C alt ©")
        assert_matches_schema(self, doc)

        ops = [op["body"] for op in doc["ast"]["operands"]]
        self.assertEqual([(n["kind"], n["symbol"]) for n in ops], [
            ("stop", "0"),
            ("final", "◉"),
            ("continue", "C"),
            ("continue", "©"),
        ])

        # If 'C' is explicitly defined in GIT, treat it as an interaction rather than continuation.
        git_with_c = {"C": ("", "A", "call", "B", "doC", [], [], "")}
        doc_c = parse_process_algebra("C >> 0", git_with_c)
        assert_matches_schema(self, doc_c)
        self.assertEqual(doc_c["ast"]["children"][0]["type"], "interaction")
        self.assertEqual(doc_c["ast"]["children"][0]["id"], "C")
        self.assertEqual(doc_c["ast"]["children"][1]["type"], "terminal")

        # Identifiers sharing prefixes with keywords should stay identifiers.
        doc_kw_prefix = parse_process_algebra("optional_step >> loop_init >> seq_1")
        assert_matches_schema(self, doc_kw_prefix)
        self.assertEqual(
            [c["id"] for c in doc_kw_prefix["ast"]["children"]],
            ["optional_step", "loop_init", "seq_1"],
        )

    def test_cross_diagram_attributes_and_pseudo_nodes(self) -> None:
        expr = (
            "([defer(ev1), invariant(x >= 0)]: i1) >> "
            "([swimlanes(Front, Back), inlane(Back), interrupt(sig), catch(err), activityFinal]: i2) >> "
            "([fork]: (i3 par i4)) >> "
            "([join]: pseudo(choice, x > 0)) >> "
            "fork(branchA, branchB) >> join"
        )
        doc = parse_process_algebra(expr, SAMPLE_GIT)
        assert_matches_schema(self, doc)

        children = doc["ast"]["children"]
        self.assertEqual(children[0]["type"], "annotated")
        self.assertEqual(
            [(a["name"], a["category"]) for a in children[0]["attributes"]],
            [("defer", "smd"), ("invariant", "smd")],
        )
        self.assertEqual(children[0]["attributes"][0]["args"], ["ev1"])

        self.assertEqual(
            [(a["name"], a["category"]) for a in children[1]["attributes"]],
            [
                ("swimlanes", "ad"),
                ("inlane", "ad"),
                ("interrupt", "ad"),
                ("catch", "ad"),
                ("activityFinal", "ad"),
            ],
        )

        # Swimlane hint from inlane(Back) should attach to i2's participants.
        lifelines_by_id = {ll["id"]: ll for ll in doc["lifelines"]}
        self.assertEqual(lifelines_by_id["AuthService"].get("swimlane"), "Back")
        self.assertEqual(lifelines_by_id["UserDB"].get("swimlane"), "Back")

        self.assertEqual(children[3]["body"]["type"], "pseudo")
        self.assertEqual(children[3]["body"]["kind"], "choice")
        self.assertEqual(children[3]["body"]["args"], ["x > 0"])
        self.assertEqual(children[4]["type"], "pseudo")
        self.assertEqual(children[4]["kind"], "fork")
        self.assertEqual(children[5]["kind"], "join")

        warning_codes = {w["code"] for w in doc["metadata"]["warnings"]}
        self.assertIn("DEGRADED_CROSS_DIAGRAM_ATTRIB", warning_codes)

    def test_lifeline_ordering_and_layout_hints(self) -> None:
        expr = "i1 >> (loop(1, 3)[retry]: (i2 >> (opt[valid]: i3))) >> (ref SessionStart alt raise[AuthFailed])"
        doc = parse_process_algebra(
            expr,
            {k: SAMPLE_GIT[k] for k in ("i1", "i2", "i3")},
            title="Login and Retry Flow",
            lifeline_roles={"Client": "actor", "UserDB": "database"},
        )
        assert_matches_schema(self, doc)

        self.assertEqual([ll["id"] for ll in doc["lifelines"]], ["Client", "AuthService", "UserDB"])
        self.assertEqual(doc["lifelines"][0]["role"], "actor")
        self.assertEqual(doc["lifelines"][2]["role"], "database")
        self.assertEqual(doc["metadata"]["title"], "Login and Retry Flow")

        hints = doc["layout_hints"]
        self.assertEqual(hints["max_label_length"], 24)
        self.assertEqual(hints["max_fragment_depth"], 2)
        self.assertEqual(
            hints["pair_spacings"],
            [
                {"from": "Client", "to": "AuthService", "max_label_length": 24},
                {"from": "AuthService", "to": "UserDB", "max_label_length": 16},
            ],
        )

    def test_git_table_loaders(self) -> None:
        # Markdown table with Greek headers
        md = """
| i | C | Ξ | N | Γ | Λ | Θ_in | Θ_out | Π |
|---|---|---|---|---|---|---|---|---|
| i1 | auth | Client | call | Server | login | user, pwd | token | log() |
| i2 | - | Server | return | Client | - | - | ok | - |
"""
        loaded_md = load_git_table(md)
        self.assertEqual(loaded_md["i1"]["label"], "[auth] login(user, pwd): token")
        self.assertEqual(loaded_md["i1"]["inputs"], ["user", "pwd"])
        self.assertEqual(loaded_md["i2"]["nature"], "return")
        self.assertEqual(loaded_md["i2"]["label"], "ok")

        # CSV input
        csv_text = (
            "id,guard,caller,nature,callee,operation,inputs,outputs,actions\n"
            "a,[ready],UI,call,API,fetch,\"id, lang\",data,\n"
        )
        loaded_csv = load_git_table(csv_text)
        self.assertEqual(loaded_csv["a"]["guard"], "ready")
        self.assertEqual(loaded_csv["a"]["inputs"], ["id", "lang"])
        self.assertEqual(loaded_csv["a"]["label"], "[ready] fetch(id, lang): data")

        # JSON list input
        json_text = json.dumps(
            [
                {
                    "id": "m1",
                    "C": "",
                    "Xi": "A",
                    "N": "combined",
                    "Gamma": "B",
                    "Lambda": "sync",
                    "Theta_in": [],
                    "Theta_out": ["ack"],
                    "Pi": "",
                }
            ]
        )
        loaded_json = load_git_table(json_text)
        self.assertEqual(loaded_json["m1"]["nature"], "combined")
        self.assertEqual(loaded_json["m1"]["label"], "sync(): ack")

    def test_unresolved_interaction_warning_and_strict_mode(self) -> None:
        doc = parse_process_algebra("i1 >> missing_id", {"i1": SAMPLE_GIT["i1"]})
        assert_matches_schema(self, doc)
        self.assertFalse(doc["ast"]["children"][1]["resolved"])
        self.assertEqual(doc["metadata"]["warnings"][0]["code"], "UNRESOLVED_INTERACTION")

        with self.assertRaises(ParseError):
            parse_process_algebra("i1 >> missing_id", {"i1": SAMPLE_GIT["i1"]}, strict_git=True)

    def test_error_cases(self) -> None:
        bad_expressions = [
            "",
            "   ",
            "(i1 >> i2",
            "i1 >> i2)",
            "(opt[unclosed: i1)",
            "raise[]",
            "(ignore[]: i1)",
            "(loop(5, 2)[bad]: i1)",
            "pseudo()",
            "ref 123",
            "i1 >>",
            "i1 @ i2",
        ]
        for expr in bad_expressions:
            with self.subTest(expr=expr):
                with self.assertRaises(ParseError):
                    parse_process_algebra(expr, SAMPLE_GIT)

        with self.assertRaises(ParseError):
            load_git_table({"bad": ("", "A", "invalid_nature", "B", "op", [], [], "")})

        with self.assertRaises(ParseError):
            load_git_table({"short": ("", "A", "call")})

    def test_cli_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            git_file = tmp_path / "git.json"
            out_file = tmp_path / "ast.json"
            git_file.write_text(json.dumps(SAMPLE_GIT), encoding="utf-8")

            exit_code = pa_parser.main(
                [
                    "--expr",
                    "i1 >> (opt[ok]: i3)",
                    "--git",
                    str(git_file),
                    "--title",
                    "CLI Test",
                    "--output",
                    str(out_file),
                ]
            )
            self.assertEqual(exit_code, 0)
            doc = json.loads(out_file.read_text(encoding="utf-8"))
            assert_matches_schema(self, doc)
            self.assertEqual(doc["metadata"]["title"], "CLI Test")


if __name__ == "__main__":
    unittest.main()
