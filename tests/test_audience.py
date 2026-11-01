"""Client edition: same per-table detail, without legend/analysis/review/questions/coverage sections."""
import tempfile
import unittest
from pathlib import Path

from oradoc import collector
from oradoc.engine import build, generate
from oradoc.i18n import S
from tests.test_engine import DATA, collect_with

REMOVED = ("h_keys", "h_indexes", "h_analysis", "h_dba", "h_questions", "h_coverage")
KEPT = ("h_overview", "h_tables", "h_relationships", "h_details")


def headings(md):
    return [l for l in md.splitlines() if l.startswith("## ")]


class AudienceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = collect_with(DATA)

    def test_client_drops_sections_and_legend(self):
        for lang in ("fa", "en"):
            with self.subTest(lang=lang):
                s = S[lang]
                md = build(self.snap, lang=lang, detail="full", audience="client")["markdown"]
                titles = " ".join(headings(md))
                for key in REMOVED:
                    self.assertNotIn(s[key].split(". ", 1)[-1], titles)
                for key in KEPT:
                    self.assertIn(s[key].split(". ", 1)[-1], titles)
                self.assertEqual(len(headings(md)), len(KEPT))
                self.assertNotIn(s["legend_title"], md)
                for tag in s["tag"].values():
                    self.assertNotIn(tag, md)
                self.assertNotIn(f"_{s['evidence']}:", md)
                self.assertIn(s["audience_names"]["client"], md)
                self.assertIn(s["erd_note_client"], md)
                self.assertNotIn("%%", md)

    def test_client_keeps_per_table_detail(self):
        tech = build(self.snap, lang="en", detail="full")["markdown"]
        client = build(self.snap, lang="en", detail="full", audience="client")["markdown"]
        tech_details = tech[tech.index("## 4. Table details"):tech.index("## 5. ")]
        client_details = client[client.index("## 4. Table details"):]
        for marker in ("| `UX_NOTE`", "- `SYS_NC00007$`", "**Primary key:**", "**CHECK constraints:**",
                       "| 1 | `ID`", "No comment recorded"):
            self.assertIn(marker, client_details)
        self.assertEqual(tech_details.count("\n| "), client_details.count("\n| "))  # same table rows

    def test_inferences_are_marked_not_presented_as_facts(self):
        md = build(self.snap, lang="en", detail="full", audience="client")["markdown"]
        lookup = next(l for l in md.splitlines() if "lookup/reference table" in l)
        self.assertTrue(lookup.startswith("- Structural interpretation: "))
        fa = build(self.snap, lang="fa", detail="full", audience="client")["markdown"]
        self.assertIn("برداشت ساختاری:", fa)

    def test_technical_edition_unchanged_by_default(self):
        default = build(self.snap, lang="fa", detail="full")
        explicit = build(self.snap, lang="fa", detail="full", audience="technical")
        self.assertEqual(default["markdown"], explicit["markdown"])
        self.assertIn(S["fa"]["legend_title"], default["markdown"])
        self.assertEqual(len(headings(default["markdown"])), 10)

    def test_client_coverage_still_validated_and_files_separate(self):
        r = build(self.snap, lang="fa", detail="full", audience="client")
        self.assertTrue(r["coverage"]["passed"])
        self.assertEqual(r["names"]["markdown"], "APP_Database_Documentation.fa.client.md")
        self.assertEqual(r["names"]["coverage"], "APP_coverage.fa.client.json")
        out = Path(tempfile.mkdtemp())
        snap_path = out / "snap.json"
        snap_path.write_text(collector.canonical_json(self.snap), encoding="utf-8")
        generate(lang="fa", detail="full", out_dir=out / "o", snapshot_path=snap_path)
        res = generate(lang="fa", detail="full", out_dir=out / "o", snapshot_path=snap_path, audience="client")
        self.assertEqual(len(res["write"]["written"]), 2)   # client markdown + client coverage only
        self.assertEqual(len(res["write"]["unchanged"]), 2)  # shared snapshot + ERD

    def test_unknown_audience_rejected(self):
        with self.assertRaises(ValueError):
            build(self.snap, lang="fa", detail="full", audience="public")


if __name__ == "__main__":
    unittest.main()
