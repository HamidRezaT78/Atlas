"""SQL Server path, offline: catalog rows -> snapshot -> analysis -> Markdown, plus profiles and the app."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from oradoc import collector, mssql_queries, webapp
from oradoc.analysis import type_label
from oradoc.config import Profile, load_config
from oradoc.engine import build
from tests.fakes import FakeConn, make_fetch

PROFILE = Profile(name="ms", dsn="db.local:1433/Sales", username="atlas_reader", keyring_service="-",
                  allowed_schemas=("dbo", "Sales"), default_schema="dbo", engine="sqlserver")


def col(table, cid, name, dtype, *, length=4, chars=None, prec=None, scale=None, null="N", default=None,
        identity="NO", computed="NO", hidden="NO"):
    return {"table_name": table, "column_id": cid, "internal_column_id": cid, "column_name": name,
            "data_type": dtype, "data_length": length, "data_precision": prec, "data_scale": scale,
            "nullable": null, "char_length": chars, "char_used": None, "data_default": default,
            "hidden_column": hidden, "virtual_column": computed, "user_generated": "YES",
            "identity_column": identity, "default_on_null": None}


def cons(table, name, ctype, *, r_owner=None, r_cons=None, r_table=None, index=None, status="ENABLED",
         validated="VALIDATED"):
    return {"table_name": table, "constraint_name": name, "constraint_type": ctype, "status": status,
            "validated": validated, "generated": "USER NAME", "deferrable": "NOT DEFERRABLE",
            "deferred": "IMMEDIATE", "delete_rule": "NO ACTION" if ctype == "R" else None, "index_name": index,
            "r_owner": r_owner, "r_constraint_name": r_cons, "r_table_name": r_table}


def ccol(table, name, column, pos=1):
    return {"table_name": table, "constraint_name": name, "column_name": column, "position": pos}


def index(table, name, unique="NONUNIQUE", typ="NONCLUSTERED", flt=None):
    return {"table_name": table, "index_owner": "dbo", "index_name": name, "index_type": typ, "uniqueness": unique,
            "status": "VALID", "visibility": "VISIBLE", "partitioned": "NO", "filter_definition": flt}


def icol(table, name, column, pos=1):
    return {"table_name": table, "index_owner": "dbo", "index_name": name, "column_name": column,
            "column_position": pos, "descend": "ASC"}


DATA = {
    "MSSQL_TABLES": [{"table_name": t, "temporary": "N", "partitioned": "NO", "iot_type": None, "nested": "NO"}
                     for t in ("Customers", "Orders")],
    "MSSQL_COLUMNS": [
        col("Customers", 1, "Id", "int", identity="YES"),
        col("Customers", 2, "Code", "varchar", length=10, chars=10),
        col("Customers", 3, "Name", "nvarchar", length=200, chars=100),
        col("Customers", 4, "Order", "int", null="Y"),
        col("Orders", 1, "Id", "bigint", length=8, identity="YES"),
        col("Orders", 2, "CustomerId", "int"),
        col("Orders", 3, "CustomerCode", "varchar", length=10, chars=10, null="Y"),
        col("Orders", 4, "Status", "nchar", length=2, chars=1, default="(N'A')"),
        col("Orders", 5, "IsPaid", "bit", length=1, default="((0))"),
        col("Orders", 6, "Amount", "decimal", length=9, prec=18, scale=2, default="((0))"),
        col("Orders", 7, "Note", "nvarchar", length=-1, chars=-1, null="Y"),
        col("Orders", 8, "CreatedAt", "datetime2", length=8, scale=3, default="(sysdatetime())"),
        col("Orders", 9, "Total", "decimal", length=9, prec=19, scale=2, computed="YES", null="Y",
            default="([Amount]*(1.09))"),
    ],
    "MSSQL_TABLE_COMMENTS": [{"table_name": "Customers", "comments": "Customer master"},
                             {"table_name": "Orders", "comments": None}],
    "MSSQL_COLUMN_COMMENTS": [{"table_name": "Orders", "column_name": "Status", "comments": "Order state"}],
    "MSSQL_CONSTRAINTS": [
        cons("Customers", "PK_Customers", "P", index="PK_Customers"),
        cons("Orders", "PK_Orders", "P", index="PK_Orders"),
        cons("Orders", "FK_Orders_Customers", "R", r_owner="dbo", r_cons="PK_Customers", r_table="Customers"),
        cons("Orders", "FK_Orders_CustomerCode", "R", r_owner="dbo", r_cons=None, r_table="Customers",
             validated="NOT VALIDATED"),
        cons("Orders", "CK_Orders_Status", "C"),
        cons("Orders", "CK_Orders_IsPaid", "C"),
    ],
    "MSSQL_FK_REFERENCED_COLUMNS": [ccol("Orders", "FK_Orders_Customers", "Id"),
                                    ccol("Orders", "FK_Orders_CustomerCode", "Code")],
    "MSSQL_CONSTRAINT_COLUMNS": [
        ccol("Customers", "PK_Customers", "Id"), ccol("Orders", "PK_Orders", "Id"),
        ccol("Orders", "FK_Orders_Customers", "CustomerId"), ccol("Orders", "FK_Orders_CustomerCode", "CustomerCode"),
        ccol("Orders", "CK_Orders_Status", "Status"), ccol("Orders", "CK_Orders_IsPaid", "IsPaid"),
    ],
    "MSSQL_CHECK_CONDITIONS": [
        {"table_name": "Orders", "constraint_name": "CK_Orders_Status", "generated": "USER NAME", "status": "ENABLED",
         "validated": "VALIDATED", "search_condition": "([Status]=N'C' OR [Status]=N'B' OR [Status]=N'A')"},
        {"table_name": "Orders", "constraint_name": "CK_Orders_IsPaid", "generated": "USER NAME", "status": "ENABLED",
         "validated": "VALIDATED", "search_condition": "([IsPaid]=(1) OR [IsPaid]=(0))"},
    ],
    "MSSQL_INDEXES": [
        index("Customers", "PK_Customers", "UNIQUE", "CLUSTERED"), index("Customers", "UX_Code", "UNIQUE"),
        index("Customers", "IX_Name"),
        index("Orders", "PK_Orders", "UNIQUE", "CLUSTERED"), index("Orders", "IX_Name"),
        index("Orders", "IX_Customer"), index("Orders", "IX_Customer_Open", flt="([Status]='A')"),
        index("Orders", "IX_Customer_Copy"),
    ],
    "MSSQL_INDEX_INCLUDED_COLUMNS": [{"table_name": "Orders", "index_name": "IX_Customer", "column_name": "Amount",
                                      "index_column_id": 2}],
    "MSSQL_INDEX_COLUMNS": [
        icol("Customers", "PK_Customers", "Id"), icol("Customers", "UX_Code", "Code"), icol("Customers", "IX_Name", "Name"),
        icol("Orders", "PK_Orders", "Id"), icol("Orders", "IX_Name", "Note"),
        icol("Orders", "IX_Customer", "CustomerId"), icol("Orders", "IX_Customer_Open", "CustomerId"),
        icol("Orders", "IX_Customer_Copy", "CustomerId"),
    ],
    "MSSQL_COUNT_TABLES": [{"n": 2}],
    "MSSQL_COUNT_COLUMNS": [{"n": 13}],
    "MSSQL_DB_VERSION": [{"product": "Microsoft SQL Server",
                          "version": "Microsoft SQL Server 15.0.2170.1 (Enterprise Edition (64-bit))"}],
}


def collect_with(data, schema="dbo"):
    conn = FakeConn(data)
    fetch = make_fetch(conn)

    @contextmanager
    def fake_connect(profile):
        yield conn

    with mock.patch.object(collector, "connect", fake_connect), mock.patch.object(collector, "fetch", fetch), \
            mock.patch.object(mssql_queries, "fetch", fetch):
        return collector.collect(PROFILE, schema), conn


class MssqlSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap, cls.conn = collect_with(DATA)
        cls.result = build(cls.snap, lang="en", detail="full")

    def test_only_sqlserver_statements_with_schema_bind(self):
        names = {name for name, _ in self.conn.calls}
        self.assertTrue(names and all(n.startswith("MSSQL_") for n in names), names)
        self.assertTrue(all(p.get("owner") == "dbo" for n, p in self.conn.calls if n != "MSSQL_DB_VERSION"))

    def test_snapshot_shape(self):
        s = self.snap
        self.assertEqual(s["engine"], "sqlserver")
        self.assertTrue(all(v["status"] == "ok" for v in s["sections"].values()), s["sections"])
        orders = s["tables"]["Orders"]
        self.assertEqual(s["tables"]["Customers"]["comment"], "Customer master")
        self.assertEqual({c["name"]: c["default"] for c in orders["columns"]}["IsPaid"], "0")
        self.assertEqual({c["name"]: c["default"] for c in orders["columns"]}["Status"], "N'A'")
        total = orders["columns"][-1]
        self.assertTrue(total["virtual"])
        self.assertEqual(total["default"], "[Amount]*(1.09)")

    def test_index_names_are_per_table(self):
        name_cols = {t: [c["name"] for ix in s["indexes"] if ix["name"] == "IX_Name" for c in ix["columns"]]
                     for t, s in self.snap["tables"].items()}
        self.assertEqual(name_cols, {"Customers": ["Name"], "Orders": ["Note"]})
        ix = {i["name"]: i for i in self.snap["tables"]["Orders"]["indexes"]}
        self.assertEqual(ix["IX_Customer"]["include"], ["Amount"])
        self.assertEqual(ix["IX_Customer_Open"]["filter"], "[Status]='A'")

    def test_fk_to_unique_index_without_constraint(self):
        rels = {r["constraint"]: r for r in self.snap["relationships"]}
        self.assertEqual(rels["FK_Orders_CustomerCode"]["target_table"], "Customers")
        self.assertEqual(rels["FK_Orders_CustomerCode"]["target_columns"], ["Code"])
        self.assertEqual(rels["FK_Orders_Customers"]["target_columns"], ["Id"])

    def test_type_labels(self):
        cols = {c["name"]: c for c in self.snap["tables"]["Orders"]["columns"]}
        self.assertEqual(type_label(cols["Note"]), "nvarchar(MAX)")
        self.assertEqual(type_label(cols["Status"]), "nchar(1)")
        self.assertEqual(type_label(cols["Amount"]), "decimal(18,2)")
        self.assertEqual(type_label(cols["CreatedAt"]), "datetime2(3)")
        self.assertEqual(type_label(cols["Id"]), "bigint")

    def test_analysis(self):
        f = self.result["findings"]
        by = lambda code: [(x["table"], x["column"], x["params"]) for x in f if x["code"] == code]  # noqa: E731
        allowed = {c: p["values"] for _, c, p in by("chk_allowed_values")}
        self.assertEqual(allowed, {"Status": ["N'C'", "N'B'", "N'A'"], "IsPaid": ["1", "0"]})
        self.assertEqual([(t, c) for t, c, _ in by("inf_flag")], [("Orders", "IsPaid")])
        self.assertEqual([(t, c) for t, c, _ in by("obs_reserved_word")], [("Customers", "Order")])
        dup = [p["index"] for _, _, p in by("obs_duplicate_index")]
        self.assertEqual(dup, [])  # same key, but different INCLUDE / filter
        self.assertEqual([p["constraint"] for _, _, p in by("obs_constraint_state")], ["FK_Orders_CustomerCode"])
        sources = {e["source"] for x in f for e in x["evidence"]}
        self.assertFalse([s for s in sources if s.startswith("ALL_")], sources)

    def test_markdown(self):
        md = self.result["markdown"]
        self.assertIn("SQL Server catalog views (`sys.*`)", md)
        self.assertIn("Microsoft SQL Server 15.0.2170.1", md)
        self.assertIn("`nvarchar(MAX)`", md)
        self.assertIn("INCLUDE (`Amount`)", md)
        self.assertIn("bracketed", md)
        self.assertNotIn("Oracle", md)
        self.assertTrue(self.result["coverage"]["passed"], self.result["coverage"])
        fa = build(self.snap, lang="fa", detail="full", audience="client")["markdown"]
        self.assertIn("SQL Server", fa)
        self.assertNotIn("Oracle", fa)

    def test_schema_case_insensitive(self):
        self.assertEqual(PROFILE.check_schema("DBO"), "dbo")
        self.assertEqual(PROFILE.check_schema("sales"), "Sales")
        with self.assertRaises(ValueError):
            PROFILE.check_schema("hr")
        snap, _ = collect_with(DATA, schema="DBO")
        self.assertEqual(snap["schema"], "dbo")

    def test_unwrap(self):
        u = mssql_queries.unwrap
        self.assertEqual(u("((0))"), "0")
        self.assertEqual(u("(getdate())"), "getdate()")
        self.assertEqual(u("([a]>(0)) AND ([b]<(1))"), "([a]>(0)) AND ([b]<(1))")  # not one enclosing pair
        self.assertIsNone(u(None))


class MssqlProfileTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.cfg = self.dir / "profiles.toml"
        self.cfg.write_text('default_profile = "x"\n', encoding="utf-8")
        self.store = {}
        kr = mock.Mock(get_password=lambda s, u: self.store.get((s, u)),
                       set_password=lambda s, u, p: self.store.__setitem__((s, u), p))
        self.patches = [mock.patch.object(webapp, "CONFIG_PATH", self.cfg), mock.patch.object(webapp, "keyring", kr)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_save_sqlserver_profile(self):
        webapp.save_profile({"engine": "sqlserver", "name": "crm", "host": "srv01\\SQL2019", "port": "",
                             "service": "Contoso CRM", "username": "doc.reader", "schemas": ["dbo", "Sales", "DBO"],
                             "password": "pw"})
        text = self.cfg.read_text(encoding="utf-8")
        self.assertIn('engine = "sqlserver"', text)
        self.assertNotIn('"pw"', text)
        p = load_config(self.cfg)["profiles"]["crm"]
        self.assertEqual((p.engine, p.dsn, p.allowed_schemas), ("sqlserver", "srv01\\SQL2019:1433/Contoso CRM", ("dbo", "Sales")))
        self.assertEqual(p.call_timeout_ms, 30000)
        self.assertEqual(self.store[("Oradoc_crm", "doc.reader")], "pw")
        listed = webapp.list_profiles()["profiles"][0]
        self.assertEqual((listed["engine"], listed["service"]), ("sqlserver", "Contoso CRM"))

    def test_oracle_profile_has_no_engine_line(self):
        webapp.save_profile({"name": "o", "host": "h", "service": "S", "username": "U", "schemas": ["app"],
                             "password": "pw"})
        self.assertNotIn("engine", self.cfg.read_text(encoding="utf-8"))
        self.assertEqual(load_config(self.cfg)["profiles"]["o"].allowed_schemas, ("APP",))

    def test_connection_fields(self):
        dsn, user, engine = webapp.connection_fields(
            {"engine": "sqlserver", "host": "10.0.0.5", "service": "", "username": "sa"}, database_optional=True)
        self.assertEqual((dsn, engine), ("10.0.0.5:1433/master", "sqlserver"))
        for bad in ({"host": "a b"}, {"service": "a/b"}, {"engine": "mysql"}):
            body = dict({"engine": "sqlserver", "host": "h", "service": "D", "username": "u"}, **bad)
            with self.subTest(bad=bad), self.assertRaises(webapp.UserError):
                webapp.connection_fields(body)

    def test_error_hints(self):
        exc = Exception("(18456, b\"Login failed for user 'u'.DB-Lib error message 20002\")")
        self.assertIn("SQL Server Authentication", webapp.friendly(exc))

    def test_test_connection_reports_databases_and_write_warning(self):
        conn = FakeConn({"MSSQL_DB_VERSION": DATA["MSSQL_DB_VERSION"],
                         "MSSQL_LIST_OWNERS": [{"owner": "dbo", "n": 3}],
                         "MSSQL_LIST_DATABASES": [{"name": "CRM"}, {"name": "Sales"}],
                         "MSSQL_PERMISSIONS": [{"sysadmin": 0, "db_owner": 1, "db_datawriter": 1, "db_ddladmin": 0}]})

        @contextmanager
        def fake_connect(profile, password=None):
            self.assertEqual(profile.engine, "sqlserver")
            yield conn

        with mock.patch.object(webapp, "connect", fake_connect), mock.patch.object(webapp, "fetch", make_fetch(conn)):
            out = webapp.test_connection({"engine": "sqlserver", "host": "h", "service": "CRM", "username": "u",
                                          "password": "pw"})
        self.assertEqual(out["databases"], ["CRM", "Sales"])
        self.assertEqual(out["owners"], [{"owner": "dbo", "tables": 3}])
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("db_owner", out["warnings"][0])
        self.assertNotIn("pw", json.dumps(out))


SERVER = Path(__file__).resolve().parent.parent / "mcpb-src" / "server" / "oracle_mcp.py"


@unittest.skipUnless(SERVER.is_file() and importlib.util.find_spec("mcp"), "needs the MCP server source and mcp package")
class MssqlServerToolsTest(unittest.TestCase):
    """The nine MCP tools on a SQL Server profile, in the shapes of the original Oracle tools."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("oracle_mcp_mssql_test", SERVER)
        cls.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.server)

    def call(self, tool, *args):
        data = dict(DATA, MSSQL_TABLE_EXISTS=lambda p: [{"table_name": t} for t in ("Customers", "Orders")
                                                        if t.casefold() == p["table_name"].casefold()])
        conn = FakeConn(data)
        fetch = make_fetch(conn)

        @contextmanager
        def fake_connect(profile):
            yield conn

        with mock.patch.object(self.server, "_profile_and_owner", lambda schema: (PROFILE, "dbo")), \
                mock.patch.object(self.server, "connect", fake_connect), \
                mock.patch.object(self.server, "fetch", fetch), mock.patch.object(mssql_queries, "fetch", fetch):
            out = json.loads(getattr(self.server, tool)(*args))
        self.assertTrue(all(n.startswith("MSSQL_") for n, _ in conn.calls))
        return out

    def test_tools(self):
        s = self.server
        self.assertEqual(self.call("list_tables"), [{"table_name": "Customers"}, {"table_name": "Orders"}])
        cols = self.call("describe_table", "orders")
        self.assertEqual([(c["column_name"], c["data_type"], c["data_length"]) for c in cols][6], ("Note", "nvarchar", -1))
        rels = self.call("list_relationships")
        self.assertIn({"source_table": "Orders", "source_column": "CustomerCode", "target_table": "Customers",
                       "target_column": "Code", "constraint_name": "FK_Orders_CustomerCode"}, rels)
        fk = [c for c in self.call("list_constraints", "Orders") if c["constraint_name"] == "FK_Orders_Customers"]
        self.assertEqual((fk[0]["column_name"], fk[0]["referenced_table"], fk[0]["referenced_column"]),
                         ("CustomerId", "Customers", "Id"))
        self.assertEqual(self.call("get_comments", "Customers")["table_comment"], "Customer master")
        self.assertEqual(self.call("get_index_expressions", "Orders"), [])
        checks = {c["constraint_name"]: c for c in self.call("get_check_constraints", "Orders")}
        self.assertEqual(checks["CK_Orders_Status"]["search_condition"], "[Status]=N'C' OR [Status]=N'B' OR [Status]=N'A'")
        self.assertEqual(checks["CK_Orders_Status"]["columns"], ["Status"])
        idx = {i["index_name"]: i for i in self.call("list_indexes", "Orders")}
        self.assertEqual((idx["PK_Orders"]["uniqueness"], idx["IX_Customer"]["column_name"]), ("UNIQUE", "CustomerId"))
        with self.assertRaises(ValueError):
            self.call("describe_table", "Missing")
        self.assertTrue(callable(s.get_column_defaults))


if __name__ == "__main__":
    unittest.main()
