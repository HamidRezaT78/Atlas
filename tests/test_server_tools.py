"""MCP tools against a fake connection: binds, allowlist, and parsing of LONG-derived values."""
import importlib.util
import json
import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from oradoc import queries
from tests.fakes import FakeConn, make_fetch

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "mcpb-src" / "server" / "oracle_mcp.py"


def load_server():
    spec = importlib.util.spec_from_file_location("oracle_mcp_under_test", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DATA = {
    "TABLE_EXISTS": lambda p: [{"n": 1 if p["table_name"] in ("USERS", "API_EXCHANGE") else 0}],
    "LEGACY_LIST_TABLES": [{"table_name": "USERS"}],
    "LEGACY_DESCRIBE_TABLE": [{"column_id": 1, "column_name": "ID"}],
    "TABLE_COMMENTS": [{"table_name": "USERS", "comments": "App users  "}],
    "COLUMN_COMMENTS": [{"table_name": "USERS", "column_name": "ID", "comments": None},
                        {"table_name": "USERS", "column_name": "MOBILE", "comments": "Mobile no."}],
    "COLUMNS": [{"table_name": "USERS", "column_id": 1, "internal_column_id": 1, "column_name": "ID",
                 "data_default": "\"APP_OWNER\".\"SEQ\".\"NEXTVAL\" \n", "virtual_column": "NO",
                 "hidden_column": "NO"}],
    "COLUMN_IDENTITY": RuntimeError("ORA-00904: invalid identifier"),
    "CONSTRAINT_COLUMNS": [{"table_name": "USERS", "constraint_name": "SYS_C1", "column_name": "ID"},
                           {"table_name": "USERS", "constraint_name": "CK_X", "column_name": "MOBILE"}],
    "CHECK_CONDITIONS": [
        {"table_name": "USERS", "constraint_name": "SYS_C1", "search_condition": '"ID" IS NOT NULL',
         "generated": "GENERATED NAME", "status": "ENABLED", "validated": "VALIDATED"},
        {"table_name": "USERS", "constraint_name": "CK_X", "search_condition": "LENGTH(MOBILE) = 11",
         "generated": "USER NAME", "status": "ENABLED", "validated": "VALIDATED"}],
    "INDEXES": [{"table_name": "API_EXCHANGE", "index_owner": "APP_OWNER", "index_name": "IX_F",
                 "index_type": "FUNCTION-BASED NORMAL", "uniqueness": "UNIQUE"},
                {"table_name": "API_EXCHANGE", "index_owner": "APP_OWNER", "index_name": "PK",
                 "index_type": "NORMAL", "uniqueness": "UNIQUE"}],
    "INDEX_COLUMNS": [{"table_name": "API_EXCHANGE", "index_owner": "APP_OWNER", "index_name": "IX_F",
                       "column_name": "SYS_NC00016$", "column_position": 1},
                      {"table_name": "API_EXCHANGE", "index_owner": "APP_OWNER", "index_name": "PK",
                       "column_name": "ID", "column_position": 1}],
    "INDEX_EXPRESSIONS": [{"table_name": "API_EXCHANGE", "index_owner": "APP_OWNER", "index_name": "IX_F",
                           "column_position": 1, "column_expression": "UPPER(\"IDEMPOTENCY_KEY\")"}],
}


@unittest.skipUnless(importlib.util.find_spec("mcp"), "the mcp package is only needed for the Claude extension")
class ServerToolsTest(unittest.TestCase):
    def setUp(self):
        os.environ["ORADOC_CONFIG"] = str(ROOT / "config" / "profiles.example.toml")
        os.environ.pop("ORADOC_PROFILE", None)
        self.conn = FakeConn(DATA)
        fetch = make_fetch(self.conn)

        @contextmanager
        def fake_connect(profile):
            yield self.conn

        self.server = load_server()
        self.patches = [
            mock.patch.object(self.server, "connect", fake_connect),
            mock.patch.object(self.server, "fetch", fetch),
            mock.patch.object(queries, "fetch", fetch),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        os.environ.pop("ORADOC_CONFIG", None)

    def test_all_tools_registered(self):
        names = {t.name for t in self.server.mcp._tool_manager.list_tools()}
        self.assertEqual(names, {
            "list_tables", "describe_table", "list_constraints", "list_indexes", "list_relationships",
            "get_comments", "get_column_defaults", "get_check_constraints", "get_index_expressions"})

    def test_legacy_tools_unchanged_binds(self):
        self.assertEqual(json.loads(self.server.list_tables()), [{"table_name": "USERS"}])
        self.assertEqual(self.conn.calls[-1], ("LEGACY_LIST_TABLES", {"owner": "APP_OWNER"}))
        json.loads(self.server.describe_table("users"))
        self.assertEqual(self.conn.calls[-1],
                         ("LEGACY_DESCRIBE_TABLE", {"owner": "APP_OWNER", "table_name": "USERS"}))

    def test_schema_allowlist_and_table_validation(self):
        with self.assertRaises(ValueError):
            self.server.list_tables(schema="SYS")
        with self.assertRaises(ValueError):
            self.server.get_comments("NOT_THERE")
        with self.assertRaises(ValueError):
            self.server.get_comments("USERS; DROP TABLE X")
        self.assertFalse(any(c[0] == "TABLE_COMMENTS" for c in self.conn.calls))

    def test_get_comments(self):
        out = json.loads(self.server.get_comments("USERS"))
        self.assertEqual(out["table_comment"], "App users")
        self.assertEqual(out["columns"][1], {"column_name": "MOBILE", "comments": "Mobile no."})

    def test_get_column_defaults_survives_pre12c(self):
        out = json.loads(self.server.get_column_defaults("USERS"))
        self.assertEqual(out["identity_info"], "unavailable")
        self.assertEqual(out["columns"][0]["data_default"], '"APP_OWNER"."SEQ"."NEXTVAL"')

    def test_get_check_constraints(self):
        out = json.loads(self.server.get_check_constraints("USERS"))
        self.assertEqual([(c["constraint_name"], c["is_not_null"]) for c in out],
                         [("SYS_C1", True), ("CK_X", False)])
        self.assertEqual(out[1]["columns"], ["MOBILE"])

    def test_get_index_expressions_only_function_based(self):
        out = json.loads(self.server.get_index_expressions("API_EXCHANGE"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["column_expression"], 'UPPER("IDEMPOTENCY_KEY")')


if __name__ == "__main__":
    unittest.main()
