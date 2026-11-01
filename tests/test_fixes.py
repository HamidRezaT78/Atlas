"""Offline tests for: no silent overwrites, function-based index ↔ hidden column links, comment wording."""
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from oradoc import collector
from oradoc.cli import main as cli_main
from oradoc.engine import OutputConflict, build, generate, write_outputs
from tests.test_engine import DATA, collect_with

EXPR = 'UPPER("NOTE")'


def snapshot_file(snap):
    path = Path(tempfile.mkdtemp()) / "APP_snapshot.json"
    path.write_text(collector.canonical_json(snap), encoding="utf-8")
    return path


def quiet(fn, *a, **kw):
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as err:
        return fn(*a, **kw), err.getvalue()


class NoSilentOverwriteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap_path = snapshot_file(collect_with(DATA))

    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "out"

    def listing(self):
        return sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*"))

    def test_conflict_detected_before_any_write(self):
        self.out.mkdir()
        md = self.out / "APP_Database_Documentation.en.md"
        md.write_text("OLD\n", encoding="utf-8")
        before = (md.read_bytes(), md.stat().st_mtime_ns)
        with self.assertRaises(OutputConflict) as cm:
            generate(lang="en", detail="standard", out_dir=self.out, snapshot_path=self.snap_path)
        self.assertEqual(cm.exception.conflicts, [str(md)])
        self.assertEqual((md.read_bytes(), md.stat().st_mtime_ns), before)
        self.assertEqual(self.listing(), ["APP_Database_Documentation.en.md"])  # nothing else written

    def test_identical_rerun_and_second_language_are_not_conflicts(self):
        first = generate(lang="en", detail="standard", out_dir=self.out, snapshot_path=self.snap_path)
        self.assertEqual(len(first["write"]["written"]), 4)
        again = generate(lang="en", detail="standard", out_dir=self.out, snapshot_path=self.snap_path)
        self.assertEqual(again["write"]["written"], [])
        self.assertEqual(len(again["write"]["unchanged"]), 4)
        fa = generate(lang="fa", detail="standard", out_dir=self.out, snapshot_path=self.snap_path)
        self.assertEqual(len(fa["write"]["written"]), 2)  # fa markdown + fa coverage
        self.assertEqual(len(fa["write"]["unchanged"]), 2)  # shared ERD + snapshot are identical
        self.assertNotIn("_backup", self.listing())

    def test_different_detail_level_is_a_conflict(self):
        generate(lang="en", detail="standard", out_dir=self.out, snapshot_path=self.snap_path)
        snapshot_before = self.listing()
        with self.assertRaises(OutputConflict) as cm:
            generate(lang="en", detail="full", out_dir=self.out, snapshot_path=self.snap_path)
        self.assertTrue(all(p.endswith((".en.md", ".en.json")) for p in cm.exception.conflicts))
        self.assertEqual(self.listing(), snapshot_before)

    def test_overwrite_backs_up_then_replaces(self):
        self.out.mkdir()
        md = self.out / "APP_Database_Documentation.en.md"
        md.write_text("OLD\n", encoding="utf-8")
        res = generate(lang="en", detail="standard", out_dir=self.out, snapshot_path=self.snap_path, overwrite=True)
        self.assertEqual(res["write"]["replaced"], [str(md)])
        backup = Path(res["write"]["backup_dir"])
        self.assertEqual(backup.parent, self.out / "_backup")
        self.assertEqual((backup / md.name).read_text(encoding="utf-8"), "OLD\n")
        self.assertIn("# Schema `APP` Documentation", md.read_text(encoding="utf-8"))

    def test_cli_reports_conflict_and_honours_overwrite(self):
        self.out.mkdir()
        md = self.out / "APP_Database_Documentation.en.md"
        md.write_text("OLD\n", encoding="utf-8")
        args = ["generate", "--from-snapshot", str(self.snap_path), "--lang", "en", "--out", str(self.out)]
        code, err = quiet(cli_main, args)
        self.assertEqual(code, 1)
        self.assertIn("nothing was written", err)
        self.assertIn(str(md), err)
        self.assertEqual(md.read_text(encoding="utf-8"), "OLD\n")
        code, _ = quiet(cli_main, args + ["--overwrite"])
        self.assertEqual(code, 0)
        self.assertNotEqual(md.read_text(encoding="utf-8"), "OLD\n")

    def test_write_outputs_preflight_covers_every_file(self):
        self.out.mkdir()
        (self.out / "b.txt").write_text("old", encoding="utf-8")
        files = {self.out / "a.txt": "new a", self.out / "b.txt": "new b", self.out / "c.txt": "new c"}
        with self.assertRaises(OutputConflict):
            write_outputs(self.out, files)
        self.assertEqual(self.listing(), ["b.txt"])  # a.txt and c.txt were not written either

    def test_run_job_overwrite_must_be_boolean(self):
        job = Path(tempfile.mkdtemp()) / "job.json"
        job.write_text(json.dumps({"from_snapshot": str(self.snap_path), "lang": "en", "out_dir": str(self.out),
                                   "overwrite": "yes"}), encoding="utf-8")
        code, err = quiet(cli_main, ["run-job", str(job)])
        self.assertEqual(code, 1)
        self.assertIn("overwrite", err)
        self.assertFalse(self.out.exists())


class FunctionBasedIndexLinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = collect_with(DATA)

    def orders_section(self, md):
        start = md.index("### ORDERS\n")
        return md[start:md.index("\n### ", start + 1)]

    def test_markdown_links_index_expression_and_hidden_column(self):
        for lang, hidden_word in (("en", "hidden system column"), ("fa", "ستون پنهان سیستمی")):
            for detail in ("standard", "full"):
                with self.subTest(lang=lang, detail=detail):
                    md = build(self.snap, lang=lang, detail=detail)["markdown"]
                    section = self.orders_section(md)
                    row = next(l for l in section.splitlines() if l.startswith("| `UX_NOTE`"))
                    self.assertIn(f"`{EXPR}`", row)
                    self.assertIn(f"{hidden_word} `SYS_NC00007$`", row)
                    link = next(l for l in section.splitlines() if l.startswith("- `SYS_NC00007$`"))
                    self.assertIn(f"`{EXPR}`", link)
                    self.assertIn("`UX_NOTE`", link)
                    summary = next(l for l in md.splitlines() if l.startswith("| `ORDERS`.`UX_NOTE`"))
                    self.assertIn("SYS_NC00007$", summary)
                    self.assertIn(EXPR, summary)

    def test_hidden_column_is_not_an_application_column(self):
        md = build(self.snap, lang="en", detail="standard")["markdown"]
        self.assertIsNone(re.search(r"^\| \d+ \| `SYS_NC00007\$`", md, re.MULTILINE))
        link = next(l for l in md.splitlines() if l.startswith("- `SYS_NC00007$`"))
        for flag in ("hidden", "virtual", "system-generated"):
            self.assertIn(flag, link)
        # the hidden column that no index uses is not listed among index links at standard detail
        self.assertNotIn("- `SYS_C00008_2601$`", md)

    def test_erd_keeps_link_as_comment_not_as_column(self):
        erd = build(self.snap, lang="en", detail="summary")["erd"]
        comment = [l for l in erd.splitlines() if l.strip().startswith("%%") and "UX_NOTE" in l]
        self.assertEqual(len(comment), 1)
        self.assertIn("SYS_NC00007$", comment[0])
        self.assertIn("hidden system column: hidden, virtual, system-generated", comment[0])
        self.assertIn(EXPR, comment[0])
        attributes = [l for l in erd.splitlines() if not l.strip().startswith("%%")]
        self.assertFalse(any("SYS_NC00007" in l for l in attributes))

    def test_expression_comes_from_metadata_and_coverage_still_passes(self):
        data = dict(DATA, INDEX_EXPRESSIONS=[dict(DATA["INDEX_EXPRESSIONS"][0], column_expression='LOWER("NOTE")')])
        r = build(collect_with(data), lang="en", detail="standard")
        self.assertIn('LOWER("NOTE")', r["markdown"])
        self.assertIn('LOWER("NOTE")', r["erd"])
        self.assertTrue(r["coverage"]["passed"])

    def test_missing_expression_is_reported_not_invented(self):
        data = dict(DATA, INDEX_EXPRESSIONS=RuntimeError("ORA-00942"),
                    COLUMNS=[dict(c, data_default=None) if c["column_name"] == "SYS_NC00007$" else c
                             for c in DATA["COLUMNS"]])
        r = build(collect_with(data), lang="en", detail="standard")
        link = next(l for l in r["markdown"].splitlines() if l.startswith("- `SYS_NC00007$`"))
        self.assertIn("not collected", link)
        self.assertIn("expression not collected", r["erd"])
        self.assertNotIn(EXPR, r["erd"])


class CommentWordingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = collect_with(DATA)

    def rows(self, md, prefix):
        return [l for l in md.splitlines() if l.startswith(prefix)]

    def test_english(self):
        md = build(self.snap, lang="en", detail="standard")["markdown"]
        kind_row = next(l for l in self.rows(md, "| ") if "[`KIND`](#kind)" in l)
        self.assertTrue(kind_row.rstrip(" |").endswith("No comment recorded"))
        id_row = next(l for l in self.rows(md, "| 1 | `ID`"))
        self.assertIn("No comment recorded", id_row)
        self.assertNotIn("unknown", id_row)
        note_row = next(l for l in self.rows(md, "| 6 | `NOTE`"))
        self.assertIn("free text", note_row)
        self.assertNotIn("No comment recorded", note_row)

    def test_persian(self):
        md = build(self.snap, lang="fa", detail="standard")["markdown"]
        kind_row = next(l for l in self.rows(md, "| ") if "[`KIND`](#kind)" in l)
        self.assertIn("توضیحی ثبت نشده", kind_row)
        self.assertNotIn("نامشخص", kind_row)
        id_row = next(l for l in self.rows(md, "| ۱ | `ID`"))
        self.assertIn("توضیحی ثبت نشده", id_row)
        self.assertNotIn("نامشخص", id_row)

    def test_failed_comment_section_is_distinct_from_null_comment(self):
        snap = collect_with(dict(DATA, COLUMN_COMMENTS=RuntimeError("ORA-01031: insufficient privileges")))
        for lang, missing, failed in (("en", "No comment recorded", "not collected (extraction failed)"),
                                      ("fa", "توضیحی ثبت نشده", "استخراج نشد (خطای بخش)")):
            with self.subTest(lang=lang):
                r = build(snap, lang=lang, detail="standard")
                md = r["markdown"]
                id_row = next(l for l in md.splitlines() if re.match(r"^\| (1|۱) \| `ID`", l))
                self.assertIn(failed, id_row)
                self.assertNotIn(missing, id_row)
                kind_row = next(l for l in md.splitlines() if "[`KIND`](#kind)" in l)
                self.assertIn(missing, kind_row)  # table comments were collected fine
                self.assertFalse(r["coverage"]["passed"])
                self.assertIn("column_comments", r["coverage"]["failed_sections"])


if __name__ == "__main__":
    unittest.main()
