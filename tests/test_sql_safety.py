"""Static guarantees: only fixed SELECTs over dictionary views, no execution path for other SQL."""
import re
import unittest
from pathlib import Path

from oradoc import mssql_queries, queries

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|GRANT|REVOKE|TRUNCATE|EXECUTE|BEGIN|"
    r"DECLARE|CALL|LOCK|COMMIT|DBMS_\w+|UTL_\w+)\b",
    re.IGNORECASE,
)
SOURCE_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_$#][\w$#.]*)", re.IGNORECASE)


class SqlSafetyTest(unittest.TestCase):
    def test_statements_found(self):
        self.assertGreaterEqual(len(queries.ALL_STATEMENTS), 15)

    def test_every_statement_is_a_dictionary_select(self):
        for name, sql in queries.ALL_STATEMENTS.items():
            with self.subTest(name=name):
                self.assertTrue(sql.strip().upper().startswith("SELECT"), name)
                self.assertNotIn(";", sql)
                self.assertIsNone(FORBIDDEN.search(sql), name)
                self.assertNotRegex(sql.upper(), r"FOR\s+UPDATE")
                sources = {s.lower() for s in SOURCE_RE.findall(sql)}
                self.assertTrue(sources, name)
                self.assertLessEqual(sources, queries.ALLOWED_VIEWS, f"{name}: {sources}")

    def test_owner_is_always_bound(self):
        for name, sql in queries.ALL_STATEMENTS.items():
            if name in ("DB_VERSION", "LIST_OWNERS"):  # no owner yet: connection test / schema picker
                continue
            with self.subTest(name=name):
                self.assertIn(":owner", sql)
                self.assertNotRegex(sql, r"['\"]\s*\|\|")  # no string concatenation

    def test_sqlserver_statements_are_catalog_selects(self):
        self.assertGreaterEqual(len(mssql_queries.ALL_STATEMENTS), 15)
        for name, sql in mssql_queries.ALL_STATEMENTS.items():
            with self.subTest(name=name):
                self.assertTrue(sql.strip().upper().startswith("SELECT"), name)
                self.assertNotIn(";", sql)
                self.assertIsNone(FORBIDDEN.search(sql), name)
                self.assertNotRegex(sql.upper(), r"\b(INTO|OPENROWSET|OPENQUERY|OPENDATASOURCE|XP_\w+|SP_\w+)\b")
                sources = {s.lower() for s in SOURCE_RE.findall(sql)}
                if name not in ("DB_VERSION", "PERMISSIONS"):  # server functions only, no FROM
                    self.assertTrue(sources, name)
                self.assertLessEqual(sources, mssql_queries.ALLOWED_VIEWS, f"{name}: {sources}")
                # the only % placeholders are the two named binds; the schema is always bound
                self.assertEqual(set(re.findall(r"%\(?\w*\)?s?", sql)) - {"%(owner)s", "%(table_name)s"}, set())
                if name not in mssql_queries.UNBOUND:
                    self.assertIn("%(owner)s", sql)
                self.assertNotRegex(sql, r"['\"]\s*\+\s*%")  # no concatenation with a bind

    def test_only_db_module_executes_sql(self):
        server = ROOT / "mcpb-src" / "server" / "oracle_mcp.py"  # absent in the standalone Tools copy
        files = list((ROOT / "oradoc").glob("*.py")) + ([server] if server.is_file() else [])
        for f in files:
            text = f.read_text(encoding="utf-8")
            with self.subTest(file=f.name):
                if f.name == "db.py":
                    self.assertEqual(text.count(".execute("), 2)  # READ ONLY + fixed statement
                else:
                    self.assertNotIn(".execute(", text)

    def test_db_session_is_read_only(self):
        text = (ROOT / "oradoc" / "db.py").read_text(encoding="utf-8")
        self.assertIn('cur.execute("SET TRANSACTION READ ONLY")', text)
        self.assertIn("conn.rollback()", text)


if __name__ == "__main__":
    unittest.main()
