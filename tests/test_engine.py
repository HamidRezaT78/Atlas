"""Engine tests on a synthetic dictionary (no Oracle): collection, analysis rules, rendering, coverage."""
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from oradoc import collector, queries
from oradoc.cli import main as cli_main
from oradoc.config import Profile
from oradoc.engine import build, generate, load_snapshot
from tests.fakes import FakeConn, make_fetch

PROFILE = Profile(name="test", dsn="secret-host:1521/SVC", username="READER", keyring_service="k",
                  allowed_schemas=("APP",), default_schema="APP")


def col(table, cid, name, dtype="NUMBER", length=22, prec=10, scale=0, nullable="Y", default=None,
        hidden="NO", virtual="NO", user_gen="YES"):
    return {"table_name": table, "column_id": cid if hidden == "NO" else None, "internal_column_id": cid,
            "column_name": name, "data_type": dtype, "data_length": length, "data_precision": prec,
            "data_scale": scale, "nullable": nullable, "char_length": 0, "char_used": None,
            "data_default": default, "hidden_column": hidden, "virtual_column": virtual, "user_generated": user_gen}


def cons(table, name, ctype, r_cons=None, index=None, generated="USER NAME"):
    return {"table_name": table, "constraint_name": name, "constraint_type": ctype, "status": "ENABLED",
            "validated": "VALIDATED", "generated": generated, "deferrable": "NOT DEFERRABLE",
            "deferred": "IMMEDIATE", "delete_rule": "NO ACTION" if ctype == "R" else None,
            "index_name": index, "r_owner": "APP" if r_cons else None, "r_constraint_name": r_cons}


def cc(table, name, column, pos=1):
    return {"table_name": table, "constraint_name": name, "column_name": column, "position": pos}


TABLES = ["ORDERS", "ORDERS_TMP", "KIND", "MATCH_A", "MATCH_B", "LOG_ONLY"]
DATA = {
    "TABLES": [{"table_name": t, "temporary": "N", "partitioned": "NO", "iot_type": None, "nested": "NO"} for t in TABLES],
    "COLUMNS": [
        col("ORDERS", 1, "ID", nullable="N", default='"APP"."ISEQ$$_1".nextval'),
        col("ORDERS", 2, "KIND_ID", nullable="N"),
        col("ORDERS", 3, "STATUS", prec=1, nullable="N"),
        col("ORDERS", 4, "STATE", prec=2),
        col("ORDERS", 5, "OWNER_ID"),
        col("ORDERS", 6, "NOTE", dtype="VARCHAR2", length=100, prec=None, scale=None),
        col("ORDERS", 7, "SYS_NC00007$", hidden="YES", virtual="YES", user_gen="NO", default='UPPER("NOTE")'),
        col("ORDERS", 8, "SYS_C00008_2601$", hidden="YES", user_gen="NO"),
        col("ORDERS_TMP", 1, "ID"), col("ORDERS_TMP", 2, "KIND_ID"), col("ORDERS_TMP", 3, "STATUS", prec=1),
        col("ORDERS_TMP", 4, "STATE", prec=2), col("ORDERS_TMP", 5, "NOTE", dtype="VARCHAR2", length=100, prec=None, scale=None),
        col("KIND", 1, "ID", prec=None, nullable="N"), col("KIND", 2, "TITLE", dtype="VARCHAR2", length=64, prec=None, scale=None),
        col("MATCH_A", 1, "ID", nullable="N"), col("MATCH_A", 2, "B_ID"),
        col("MATCH_B", 1, "ID", nullable="N"), col("MATCH_B", 2, "A_ID"),
        col("LOG_ONLY", 1, "USER", dtype="VARCHAR2", length=30, prec=None, scale=None),
    ],
    "COLUMN_IDENTITY": [{"table_name": "ORDERS", "column_name": "ID", "identity_column": "YES", "default_on_null": "NO"}],
    "TABLE_COMMENTS": [{"table_name": "ORDERS", "comments": "Customer orders | v2"}] +
                      [{"table_name": t, "comments": None} for t in TABLES if t != "ORDERS"],
    "COLUMN_COMMENTS": [{"table_name": "ORDERS", "column_name": "NOTE", "comments": "free text"}],
    "CONSTRAINTS": [
        cons("ORDERS", "PK_ORDERS", "P", index="PK_ORDERS"),
        cons("ORDERS", "FK_ORDERS_KIND", "R", r_cons="PK_KIND"),
        cons("ORDERS", "CK_ORDERS_STATUS", "C"),
        cons("ORDERS", "CK_ORDERS_STATE", "C"),
        cons("ORDERS", "SYS_C1", "C", generated="GENERATED NAME"),
        cons("KIND", "PK_KIND", "P", index="PK_KIND"),
        cons("MATCH_A", "PK_A", "P", index="PK_A"), cons("MATCH_A", "FK_A_B", "R", r_cons="PK_B"),
        cons("MATCH_B", "PK_B", "P", index="PK_B"), cons("MATCH_B", "FK_B_A", "R", r_cons="PK_A"),
    ],
    "CONSTRAINT_COLUMNS": [
        cc("ORDERS", "PK_ORDERS", "ID"), cc("ORDERS", "FK_ORDERS_KIND", "KIND_ID"),
        cc("ORDERS", "CK_ORDERS_STATUS", "STATUS"), cc("ORDERS", "CK_ORDERS_STATE", "STATE"),
        cc("ORDERS", "SYS_C1", "ID"), cc("KIND", "PK_KIND", "ID"),
        cc("MATCH_A", "PK_A", "ID"), cc("MATCH_A", "FK_A_B", "B_ID"),
        cc("MATCH_B", "PK_B", "ID"), cc("MATCH_B", "FK_B_A", "A_ID"),
    ],
    "CHECK_CONDITIONS": [
        {"table_name": "ORDERS", "constraint_name": "CK_ORDERS_STATUS", "search_condition": "STATUS IN (0,1)",
         "generated": "USER NAME", "status": "ENABLED", "validated": "VALIDATED"},
        {"table_name": "ORDERS", "constraint_name": "CK_ORDERS_STATE", "search_condition": "STATE IN (1, 2, 3)",
         "generated": "USER NAME", "status": "ENABLED", "validated": "VALIDATED"},
        {"table_name": "ORDERS", "constraint_name": "SYS_C1", "search_condition": '"ID" IS NOT NULL',
         "generated": "GENERATED NAME", "status": "ENABLED", "validated": "VALIDATED"},
    ],
    "INDEXES": [
        {"table_name": "ORDERS", "index_owner": "APP", "index_name": "PK_ORDERS", "index_type": "NORMAL",
         "uniqueness": "UNIQUE", "status": "VALID", "visibility": "VISIBLE", "partitioned": "NO"},
        {"table_name": "ORDERS", "index_owner": "APP", "index_name": "UX_NOTE", "index_type": "FUNCTION-BASED NORMAL",
         "uniqueness": "UNIQUE", "status": "VALID", "visibility": "VISIBLE", "partitioned": "NO"},
        {"table_name": "KIND", "index_owner": "APP", "index_name": "PK_KIND", "index_type": "NORMAL",
         "uniqueness": "UNIQUE", "status": "VALID", "visibility": "VISIBLE", "partitioned": "NO"},
        {"table_name": "MATCH_A", "index_owner": "APP", "index_name": "PK_A", "index_type": "NORMAL",
         "uniqueness": "UNIQUE", "status": "VALID", "visibility": "VISIBLE", "partitioned": "NO"},
        {"table_name": "MATCH_B", "index_owner": "APP", "index_name": "PK_B", "index_type": "NORMAL",
         "uniqueness": "UNIQUE", "status": "VALID", "visibility": "VISIBLE", "partitioned": "NO"},
    ],
    "INDEX_COLUMNS": [
        {"table_name": "ORDERS", "index_owner": "APP", "index_name": "PK_ORDERS", "column_name": "ID", "column_position": 1, "descend": "ASC"},
        {"table_name": "ORDERS", "index_owner": "APP", "index_name": "UX_NOTE", "column_name": "SYS_NC00007$", "column_position": 1, "descend": "ASC"},
        {"table_name": "KIND", "index_owner": "APP", "index_name": "PK_KIND", "column_name": "ID", "column_position": 1, "descend": "ASC"},
        {"table_name": "MATCH_A", "index_owner": "APP", "index_name": "PK_A", "column_name": "ID", "column_position": 1, "descend": "ASC"},
        {"table_name": "MATCH_B", "index_owner": "APP", "index_name": "PK_B", "column_name": "ID", "column_position": 1, "descend": "ASC"},
    ],
    "INDEX_EXPRESSIONS": [{"table_name": "ORDERS", "index_owner": "APP", "index_name": "UX_NOTE",
                           "column_position": 1, "column_expression": 'UPPER("NOTE")'}],
    "COUNT_TABLES": [{"n": 6}],
    "COUNT_COLUMNS": [{"n": 18}],
    "DB_VERSION": [{"product": "Oracle Database 19c Enterprise Edition", "version": "19.0.0.0.0"}],
}


def collect_with(data):
    conn = FakeConn(data)
    fetch = make_fetch(conn)

    @contextmanager
    def fake_connect(profile):
        yield conn

    with mock.patch.object(collector, "connect", fake_connect), mock.patch.object(collector, "fetch", fetch), \
            mock.patch.object(queries, "fetch", fetch):
        return collector.collect(PROFILE, "APP")


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = collect_with(DATA)

    def codes(self, findings, code):
        return [(f["table"], f["column"]) for f in findings if f["code"] == code]

    def test_snapshot_shape(self):
        s = self.snap
        self.assertEqual(sorted(s["tables"]), sorted(TABLES))
        orders = s["tables"]["ORDERS"]
        self.assertEqual([c["name"] for c in orders["columns"]], ["ID", "KIND_ID", "STATUS", "STATE", "OWNER_ID", "NOTE"])
        self.assertEqual(len(orders["hidden_columns"]), 2)
        self.assertTrue(orders["columns"][0]["identity"])
        self.assertEqual(orders["indexes"][1]["columns"][0]["expression"], 'UPPER("NOTE")')
        self.assertEqual(len(s["relationships"]), 3)
        self.assertNotIn("secret-host", json.dumps(s))
        self.assertTrue(all(v["status"] == "ok" for v in s["sections"].values()))

    def test_analysis_rules(self):
        f = build(self.snap, lang="en", detail="full")["findings"]
        self.assertEqual(self.codes(f, "inf_flag"), [("ORDERS", "STATUS")])
        self.assertEqual(self.codes(f, "inf_enum"), [("ORDERS", "STATE")])
        self.assertEqual(self.codes(f, "inf_lookup"), [("KIND", None)])
        self.assertEqual([x["params"]["other"] for x in f if x["code"] == "inf_copy_of"], ["ORDERS"])
        self.assertEqual(len([x for x in f if x["code"] == "inf_match_link"]), 1)
        self.assertIn(("ORDERS", "OWNER_ID"), self.codes(f, "q_id_like_no_fk"))
        self.assertNotIn(("ORDERS", "KIND_ID"), self.codes(f, "q_id_like_no_fk"))
        self.assertEqual(self.codes(f, "obs_hidden_system_column"), [("ORDERS", "SYS_C00008_2601$")])
        self.assertEqual(self.codes(f, "obs_reserved_word"), [("LOG_ONLY", "USER")])
        self.assertIn(("ORDERS", None), self.codes(f, "obs_unique_index_no_constraint"))
        self.assertEqual([x["params"]["constraint"] for x in f if x["code"] == "obs_fk_type_mismatch"], ["FK_ORDERS_KIND"])
        for x in f:
            self.assertIn(x["kind"], ("verified", "inferred", "question"))
            if x["kind"] == "inferred":
                self.assertTrue(x["evidence"], x)

    def test_name_alone_never_infers(self):
        data = dict(DATA)
        data["COLUMNS"] = DATA["COLUMNS"] + [col("STATUS_TYPE", 1, "ID", nullable="N"),
                                             col("STATUS_TYPE", 2, "TITLE", dtype="VARCHAR2", length=10, prec=None, scale=None)]
        data["TABLES"] = DATA["TABLES"] + [{"table_name": "STATUS_TYPE", "temporary": "N", "partitioned": "NO",
                                            "iot_type": None, "nested": "NO"}]
        f = build(collect_with(data), lang="en", detail="full")["findings"]
        self.assertFalse([x for x in f if x["kind"] == "inferred" and x["table"] == "STATUS_TYPE"])

    def test_render_all_options_and_coverage(self):
        for lang in ("fa", "en"):
            for detail in ("summary", "standard", "full"):
                with self.subTest(lang=lang, detail=detail):
                    r = build(self.snap, lang=lang, detail=detail)
                    self.assertTrue(r["coverage"]["passed"], r["coverage"])
                    md = r["markdown"]
                    self.assertNotIn("secret-host", md)
                    self.assertIn("```mermaid", md)
                    for t in TABLES:
                        self.assertIn(f"`{t}`", md)
                    if detail != "summary":
                        self.assertIn("Customer orders \\| v2", md)
                        self.assertIn('UPPER("NOTE")', md)
                        self.assertIn("ISEQ$$_1", md)
                    self.assertTrue(r["erd"].startswith("erDiagram"))
                    self.assertIn("NUMBER_10_0 KIND_ID FK", r["erd"])

    def test_deterministic(self):
        a = build(self.snap, lang="fa", detail="full")
        b = build(collect_with(DATA), lang="fa", detail="full")
        self.assertEqual(a["markdown"], b["markdown"])
        self.assertEqual(a["erd"], b["erd"])

    def test_failed_section_is_reported_not_hidden(self):
        data = dict(DATA, INDEX_EXPRESSIONS=RuntimeError("ORA-00942 at secret-host:1521/SVC"))
        snap = collect_with(data)
        self.assertEqual(snap["sections"]["index_expressions"]["status"], "failed")
        self.assertNotIn("secret-host", snap["sections"]["index_expressions"]["error"])
        r = build(snap, lang="en", detail="standard")
        self.assertFalse(r["coverage"]["passed"])
        self.assertIn("index_expressions", r["coverage"]["failed_sections"])
        self.assertIn("**failed**", r["markdown"])

    def test_count_mismatch_fails(self):
        snap = collect_with(dict(DATA, COUNT_COLUMNS=[{"n": 19}]))
        self.assertFalse(build(snap, lang="en", detail="standard")["coverage"]["items"]["columns"]["ok"])

    def test_generate_files_and_snapshot_roundtrip(self):
        out = Path(tempfile.mkdtemp())
        snap_path = out / "in.json"
        snap_path.write_text(collector.canonical_json(self.snap), encoding="utf-8")
        ann = out / "ann.json"
        ann.write_text(json.dumps({"tables": {"KIND": {"text": "Order kinds", "source": "team"}},
                                   "columns": {"NOPE.X": {"text": "x"}}}), encoding="utf-8")
        res = generate(lang="en", detail="standard", out_dir=out / "o", snapshot_path=snap_path, annotations_path=ann)
        md = Path(res["files"]["markdown"]).read_text(encoding="utf-8")
        self.assertIn("[user-provided] Order kinds", md)
        self.assertEqual(res["coverage"]["annotations_unmatched"], ["NOPE.X"])
        self.assertEqual(load_snapshot(res["files"]["snapshot"])["fingerprint"], self.snap["fingerprint"])
        tampered = json.loads(snap_path.read_text(encoding="utf-8"))
        tampered["tables"]["KIND"]["comment"] = "changed"
        snap_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_snapshot(snap_path)

    def test_run_job_rejects_unknown_keys(self):
        job = Path(tempfile.mkdtemp()) / "job.json"
        job.write_text(json.dumps({"schema": "APP", "password": "x"}), encoding="utf-8")
        self.assertEqual(cli_main(["run-job", str(job)]), 1)


if __name__ == "__main__":
    unittest.main()
