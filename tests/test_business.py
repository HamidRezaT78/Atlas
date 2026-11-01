"""Business analysis: naming rules, roles, modules, processes, rendering, and the Claude layer (no network)."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from oradoc import business_ai, webapp
from oradoc.business import analyze_business, name_phrase, phrase, split_name, words
from oradoc.business_render import render_business
from oradoc.collector import canonical_json, fingerprint
from oradoc.engine import generate_business


def col(name, dtype="NUMBER", *, prec=None, scale=None, length=22, null=True, comment=None):
    return {"name": name, "column_id": 1, "data_type": dtype, "data_length": length, "data_precision": prec,
            "data_scale": scale, "char_length": length if dtype.startswith("VARCHAR") else None, "char_used": None,
            "nullable": null, "default": None, "virtual": False, "hidden": False, "user_generated": True,
            "identity": False, "default_on_null": None, "comment": comment}


AUDIT = [col("CREATED_AT", "DATE"), col("CREATED_BY", "VARCHAR2"), col("MODIFIED_AT", "DATE"), col("MODIFIED_BY", "VARCHAR2")]


def table(name, cols, *, pk=("ID",), fks=(), comment=None, checks=()):
    cons = [{"name": f"PK_{name}", "type": "P", "columns": list(pk), "status": "ENABLED", "validated": "VALIDATED",
             "generated": "USER NAME", "deferrable": None, "deferred": None, "delete_rule": None, "index_name": None}] if pk else []
    for i, (c, tgt) in enumerate(fks):
        cons.append({"name": f"FK_{name}_{i}", "type": "R", "columns": [c], "status": "ENABLED", "validated": "VALIDATED",
                     "generated": "USER NAME", "deferrable": None, "deferred": None, "delete_rule": "NO ACTION",
                     "index_name": None, "ref_owner": "APP", "ref_constraint": f"PK_{tgt}", "ref_table": tgt,
                     "ref_columns": ["ID"]})
    for i, (c, cond) in enumerate(checks):
        cons.append({"name": f"CK_{name}_{i}", "type": "C", "columns": [c], "status": "ENABLED", "validated": "VALIDATED",
                     "generated": "USER NAME", "deferrable": None, "deferred": None, "delete_rule": None,
                     "index_name": None, "condition": cond, "is_not_null": False})
    return {"name": name, "temporary": "N", "partitioned": "NO", "iot_type": None, "nested": "NO", "comment": comment,
            "columns": [col("ID", null=False)] + cols, "hidden_columns": [], "constraints": cons, "indexes": []}


def snapshot():
    tx = [col("INVOICE_NUMBER", "VARCHAR2"), col("PAID_AMOUNT", "NUMBER", prec=18, scale=0),
          col("PAYMENT_DATE_TIME", "DATE")]
    tables = [
        table("ORDER_CHANNEL", [col("CHANNEL_NO", "VARCHAR2"), col("COURIER_ID"), col("IS_ACTIVATED", prec=1, scale=0)] + AUDIT,
              fks=[("COURIER_ID", "COURIER")]),
        table("COURIER", [col("NATIONAL_CODE", "VARCHAR2"), col("FULL_NAME", "VARCHAR2"), col("VEHICLE_TYPE_ID"),
                            col("CORPORATON_TYPE_ID")] + AUDIT,
              fks=[("VEHICLE_TYPE_ID", "VEHICLE_TYPE"), ("CORPORATON_TYPE_ID", "CORPERATION_TYPE")],
              comment="اطلاعات پیک‌های فعال"),
        table("VEHICLE_TYPE", [col("TITLE", "VARCHAR2")] + AUDIT),
        table("CORPERATION_TYPE", [col("TITLE", "VARCHAR2")] + AUDIT),
        table("ORDER_PAYMENT", [col("ORDER_CHANNEL_ID"), col("API_EXCHANGE_ID")] + tx + AUDIT,
              fks=[("ORDER_CHANNEL_ID", "ORDER_CHANNEL"), ("API_EXCHANGE_ID", "API_EXCHANGE")]),
        table("ORDER_PAYMENT_TMP", [col("ORDER_CHANNEL_ID")] + tx, pk=()),
        table("ORDER_PAYMENT_REJECT_LOG", [col("PAYMENT_ID"), col("CREATED_AT", "DATE")] + tx),
        table("ORDER_PAYMENT_CHECKPOINT", [col("ORDER_CHANNEL_ID"), col("RANGE_START_DATE", "DATE"),
                                              col("RANGE_END_DATE", "DATE"), col("FETCHED_COUNT"), col("STATUS")] + AUDIT,
              fks=[("ORDER_CHANNEL_ID", "ORDER_CHANNEL")]),
        table("ORDER_RECONCILIATON", [col("ORDER_CHANNEL_ID"), col("TOTAL_MATCHED_COUNT"), col("RECONCILIATON_STATUS")] + AUDIT),
        table("ORDER_REFUND", [col("ORDER_CHANNEL_ID"), col("REFUND_AMOUNT", prec=18, scale=0), col("REFUND_STATUS"),
                                   col("API_EXCHANGE_ID")] + AUDIT,
              fks=[("ORDER_CHANNEL_ID", "ORDER_CHANNEL"), ("API_EXCHANGE_ID", "API_EXCHANGE")]),
        table("ORDER_NOTICE_SMS_OUTBOX", [col("ORDER_REFUND_ID"), col("MESSAGE_TEXT", "VARCHAR2"), col("STATUS"),
                                         col("ATTEMPT_COUNT"), col("NEXT_ATTEMPT_AT", "DATE"), col("LEASE_UNTIL", "DATE"),
                                         col("LEASE_TOKEN", "VARCHAR2")],
              checks=[("STATUS", "STATUS IN (0,1,2)")]),
        table("API_EXCHANGE", [col("REQUEST_JSON", "CLOB"), col("RESPONSE_JSON", "CLOB"),
                                      col("TRACKING_CODE", "VARCHAR2"), col("IDEMPOTENCY_KEY", "VARCHAR2")] + AUDIT),
        table("DEPOT", [col("TITLE", "VARCHAR2"), col("CONTRCAT_DATE", "DATE")] + AUDIT),
        table("DEPOT_DOCK", [col("DEPOT_ID"), col("DOCK_CODE", "VARCHAR2"), col("STATUS")] + AUDIT,
              fks=[("DEPOT_ID", "DEPOT")]),
        table("USERS", [col("USERNAME", "VARCHAR2"), col("PASSWORD_HASH", "VARCHAR2"), col("MOBILE", "VARCHAR2")] + AUDIT),
        table("ACTION_LOG", [col("USER", "VARCHAR2"), col("ACTION", "VARCHAR2"), col("OLDVALUE", "VARCHAR2"),
                             col("NEWVALUE", "VARCHAR2")]),
    ]
    rels = []
    for t in tables:
        for c in t["constraints"]:
            if c["type"] == "R":
                rels.append({"constraint": c["name"], "source_table": t["name"], "source_columns": c["columns"],
                             "target_owner": "APP", "target_table": c["ref_table"], "target_columns": ["ID"],
                             "delete_rule": "NO ACTION", "status": "ENABLED", "validated": "VALIDATED", "external": False})
    snap = {"format": 1, "schema": "APP", "profile": "test", "db_version": None, "counts": {}, "sections": {},
            "tables": {t["name"]: t for t in tables}, "relationships": rels}
    snap["fingerprint"] = fingerprint(snap)
    return snap


class NamingTest(unittest.TestCase):
    def test_split_and_phrase(self):
        self.assertEqual(split_name("AssessmentQuestionOption"), ["assessment", "question", "option"])
        self.assertEqual(split_name("ORDER_PAYMENT_TMP"), ["order", "payment", "tmp"])
        self.assertEqual(name_phrase("ORDER_PAYMENT", "fa"), "پرداخت سفارش")
        self.assertEqual(name_phrase("ORDER_PAYMENT_TMP", "fa"), "پرداخت سفارش موقت")
        self.assertEqual(name_phrase("LAST_BALANCE", "fa"), "آخرین مانده")
        self.assertEqual(name_phrase("ORDER_PAYMENT", "en"), "Order Payment")
        self.assertEqual(phrase(words("ROLE_LEVELS"), "fa"), "سطح نقش")

    def test_misspellings(self):
        self.assertEqual(words("ACCOUNT_RECONCILIATON"), ["account", "reconciliation"])  # one clear correction
        self.assertEqual(words("CORPERATION_TYPE"), ["corperation", "type"])  # cooperation or corporation: keep
        self.assertEqual(words("IMPORTED_COUNT"), ["import", "count"])  # inflection, not a typo


class RulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = snapshot()
        cls.biz = analyze_business(cls.snap)

    def role(self, t):
        return self.biz["tables"][t]["role"]

    def test_roles(self):
        expected = {"ORDER_CHANNEL": "master", "COURIER": "master", "VEHICLE_TYPE": "lookup",
                    "ORDER_PAYMENT": "transaction", "ORDER_PAYMENT_TMP": "staging",
                    "ORDER_PAYMENT_REJECT_LOG": "reject_log", "ORDER_PAYMENT_CHECKPOINT": "checkpoint",
                    "ORDER_RECONCILIATON": "reconciliation", "ORDER_REFUND": "transaction",
                    "ORDER_NOTICE_SMS_OUTBOX": "outbox", "API_EXCHANGE": "integration_log",
                    "DEPOT_DOCK": "detail", "USERS": "security", "ACTION_LOG": "audit_log"}
        self.assertEqual({t: self.role(t) for t in expected}, expected)
        self.assertEqual(self.biz["tables"]["ORDER_PAYMENT_TMP"]["role_params"]["base"], "ORDER_PAYMENT")

    def test_implicit_relations(self):
        imp = {(i["table"], i["column"]): i["target"] for i in self.biz["implicit_relations"]}
        self.assertEqual(imp[("ORDER_PAYMENT_REJECT_LOG", "PAYMENT_ID")], "ORDER_PAYMENT")
        self.assertEqual(imp[("ORDER_NOTICE_SMS_OUTBOX", "ORDER_REFUND_ID")], "ORDER_REFUND")
        self.assertEqual(imp[("ORDER_RECONCILIATON", "ORDER_CHANNEL_ID")], "ORDER_CHANNEL")
        self.assertNotIn(("ORDER_PAYMENT", "ORDER_CHANNEL_ID"), imp)  # declared FK, not implicit

    def test_modules(self):
        mods = {m["key"]: set(m["tables"]) for m in self.biz["modules"]}
        self.assertEqual(mods["courier"], {"COURIER", "VEHICLE_TYPE", "CORPERATION_TYPE"})
        self.assertIn("ORDER_PAYMENT_TMP", mods["order"])
        self.assertEqual(mods["depot"], {"DEPOT", "DEPOT_DOCK"})
        self.assertEqual(sum(len(v) for v in mods.values()), len(self.snap["tables"]))  # every table, once

    def test_processes_quality_sensitive(self):
        codes = {p["code"] for p in self.biz["processes"]}
        self.assertLessEqual({"proc_ingest", "proc_reconcile", "proc_outbox", "proc_integration", "proc_master_detail",
                              "proc_access", "proc_audit", "proc_lifecycle"}, codes)
        ingest = next(p for p in self.biz["processes"] if p["code"] == "proc_ingest")["params"]
        self.assertEqual((ingest["core"], ingest["staging"], ingest["reject"], ingest["checkpoint"]),
                         ("ORDER_PAYMENT", "ORDER_PAYMENT_TMP", "ORDER_PAYMENT_REJECT_LOG",
                          "ORDER_PAYMENT_CHECKPOINT"))
        life = {(p["params"]["table"], p["params"]["column"]): p["params"]["values"]
                for p in self.biz["processes"] if p["code"] == "proc_lifecycle"}
        self.assertEqual(life[("ORDER_NOTICE_SMS_OUTBOX", "STATUS")], ["0", "1", "2"])
        typos = {q["params"]["token"]: q["params"]["suggest"] for q in self.biz["quality"] if q["code"] == "q_typo"}
        self.assertEqual(typos["RECONCILIATON"], ["RECONCILIATION"])
        self.assertEqual(typos["CONTRCAT"], ["CONTRACT"])
        self.assertEqual(typos["CORPERATION"], ["COOPERATION", "CORPORATION"])
        mism = [q["params"]["column"] for q in self.biz["quality"] if q["code"] == "q_spelling_mismatch"]
        self.assertEqual(mism, ["CORPORATON_TYPE_ID"])
        kinds = {(x["table"], x["column"]): x["kind"] for x in self.biz["sensitive"]}
        self.assertEqual(kinds[("COURIER", "NATIONAL_CODE")], "national_id")
        self.assertEqual(kinds[("USERS", "PASSWORD_HASH")], "secret")
        self.assertNotIn(("ORDER_NOTICE_SMS_OUTBOX", "LEASE_TOKEN"), kinds)  # a processing lease, not a credential

    def test_render_both_languages(self):
        for lang in ("fa", "en"):
            md, cov = render_business(self.snap, self.biz, lang=lang)
            with self.subTest(lang=lang):
                self.assertTrue(cov["passed"], cov)
                self.assertEqual(md.count("```mermaid"), 1)
                for t in self.snap["tables"]:
                    self.assertIn(f"`{t}`", md)
                self.assertNotIn("{", md.split("```mermaid")[0])  # no unfilled template field
        fa, _ = render_business(self.snap, self.biz, lang="fa")
        self.assertIn("برداشت بیزنسی", fa)
        self.assertIn("«پرداخت سفارش موقت» (`ORDER_PAYMENT_TMP`)", fa)
        self.assertIn("اطلاعات پیک‌های فعال", fa)  # recorded comment is used

    def test_deterministic(self):
        self.assertEqual(render_business(self.snap, analyze_business(snapshot()), lang="fa")[0],
                         render_business(self.snap, self.biz, lang="fa")[0])


def fake_response(payload, stop="end_turn", tokens=(1000, 200)):
    return SimpleNamespace(stop_reason=stop, usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
                           content=[SimpleNamespace(type="text", text=json.dumps(payload))])


class FakeClient:
    def __init__(self, handler):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))
        self.handler = handler

    def create(self, **kw):
        self.calls.append(kw)
        return self.handler(kw, len(self.calls))


def describe_all(kw, n):
    content = kw["messages"][0]["content"]
    if "OVERVIEW" in kw["system"] or "MODULES (key" in content:
        return fake_response({"domain": "مدیریت سفارش", "summary": "سامانه سفارش.", "questions": ["پرسش؟"],
                              "modules": [{"key": "order", "name": "سفارش‌ها", "description": "شرح ماژول."},
                                          {"key": "nope", "name": "x", "description": "y"}],
                              "processes": [{"name": "بازپرداخت سفارش", "description": "شرح.",
                                             "tables": ["ORDER_REFUND", "GHOST"]}]})
    names = [line.split()[1] for line in content.splitlines() if line.startswith("TABLE ")]
    return fake_response({"tables": [{"table": t, "business_name": f"نام {t}", "description": f"شرح {t}.",
                                      "columns": [{"column": "ID", "meaning": "شناسه"}, {"column": "NOPE", "meaning": "x"}]}
                                     for t in names] + [{"table": "GHOST", "business_name": "x", "description": "y",
                                                         "columns": []}]})


class AiTest(unittest.TestCase):
    def setUp(self):
        self.snap = snapshot()
        self.biz = analyze_business(self.snap)

    def run_enrich(self, handler):
        fake = FakeClient(handler)
        with mock.patch.object(business_ai, "client", lambda key: fake):
            out = business_ai.enrich(self.snap, self.biz, key="sk-ant-test", lang="fa", log=lambda m: None)
        return out, fake

    def test_request_shape_and_merge(self):
        out, fake = self.run_enrich(describe_all)
        kw = fake.calls[0]
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual((kw["fallbacks"], kw["betas"]), ("default", ["server-side-fallback-2026-07-01"]))
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("temperature", kw)
        sent = " ".join(c["messages"][0]["content"] for c in fake.calls)
        self.assertIn("ORDER_PAYMENT", sent)
        self.assertEqual(set(out["tables"]), set(self.snap["tables"]))  # GHOST ignored
        self.assertEqual(out["tables"]["ORDER_CHANNEL"]["columns"], {"ID": "شناسه"})  # unknown column dropped
        self.assertEqual(set(out["modules"]), {"order"})
        self.assertEqual(out["processes"][0]["tables"], ["ORDER_REFUND"])
        self.assertEqual(out["usage"]["requests"], len(fake.calls))
        self.assertGreater(out["usage"]["cost_usd"], 0)
        md, cov = render_business(self.snap, self.biz, lang="fa", ai=out)
        self.assertTrue(cov["passed"])
        self.assertIn("نام ORDER_CHANNEL", md)
        self.assertIn("سفارش‌ها", md)
        self.assertIn("claude-opus-5-5", md)

    def test_max_tokens_splits_batch_and_refusal_is_reported(self):
        state = {"first": True}

        def handler(kw, n):
            content = kw["messages"][0]["content"]
            if "MODULES (key" in content:
                return fake_response({}, stop="refusal")
            if state["first"]:
                state["first"] = False
                return fake_response({}, stop="max_tokens")
            return describe_all(kw, n)

        out, fake = self.run_enrich(handler)
        self.assertEqual(set(out["tables"]), set(self.snap["tables"]))  # the halves succeeded
        self.assertIn("overview: refusal", out["warnings"])
        self.assertEqual(out["summary"], "")

    def test_generate_business_caches_and_falls_back(self):
        d = Path(tempfile.mkdtemp())
        snap_path = d / "APP_snapshot.json"
        snap_path.write_text(canonical_json(self.snap) + "\n", encoding="utf-8")
        fake = FakeClient(describe_all)
        with mock.patch.object(business_ai, "client", lambda key: fake):
            r1 = generate_business(snapshot_path=snap_path, lang="fa", ai=True, ai_key="sk-ant-x", log=lambda m: None)
            n = len(fake.calls)
            (d / "APP_Business_Analysis.fa.md").unlink()
            r2 = generate_business(snapshot_path=snap_path, lang="fa", ai=True, ai_key="sk-ant-x", log=lambda m: None)
        self.assertTrue(r1["passed"] and r2["passed"])
        self.assertEqual(len(fake.calls), n)  # second run used the cache: no new requests
        self.assertTrue((d / "APP_business_ai.fa.json").is_file())

        def boom(key):
            raise business_ai.AIError("کلید API نامعتبر است.")

        d2 = Path(tempfile.mkdtemp())
        (d2 / "APP_snapshot.json").write_text(canonical_json(self.snap) + "\n", encoding="utf-8")
        with mock.patch.object(business_ai, "enrich", lambda *a, **k: boom(None)):
            r3 = generate_business(snapshot_path=d2 / "APP_snapshot.json", lang="fa", ai=True, ai_key="sk-ant-x",
                                   log=lambda m: None)
        self.assertTrue(r3["passed"])
        self.assertIsNone(r3["ai"])
        self.assertTrue(any("کلید API نامعتبر" in w for w in r3["warnings"]))
        self.assertNotIn("هوش مصنوعی (", Path(r3["markdown"]).read_text(encoding="utf-8").split("\n")[4])

    def test_webapp_key_validation_and_job_guard(self):
        with self.assertRaises(webapp.UserError):
            webapp.ai_key_save({"key": "not-a-key"})
        with mock.patch.object(webapp, "ai_key_status", lambda: {"has_key": False, "model": "m"}), \
                mock.patch.object(webapp, "existing_profile", lambda n: mock.Mock(
                    check_schema=lambda s: "APP", dsn="h:1/S", engine="oracle")), \
                mock.patch.object(webapp, "has_password", lambda p: True):
            with self.assertRaises(webapp.UserError):
                webapp.start_job({"profile": "p", "schema": "APP", "langs": ["fa"], "audiences": ["technical"],
                                  "business_ai": True})


class JobTest(unittest.TestCase):
    """The local app's job runs the business step after the documents (database read is faked)."""

    def test_job_writes_business_document(self):
        from tests.test_mssql import DATA, PROFILE, collect_with
        snap, _ = collect_with(DATA)
        root = Path(tempfile.mkdtemp())
        with mock.patch.object(webapp, "collect", lambda profile, schema: snap), \
                mock.patch.object(webapp, "DEFAULT_DOCS_ROOT", root), mock.patch.dict(webapp.JOB, {}, clear=True):
            webapp.JOB.update({"state": "running", "log": [], "outputs": [], "folders": [], "warnings": [],
                               "steps": [{"label": x, "status": "pending"} for x in ("read", "doc", "biz-fa", "biz-en")]})
            webapp._run_job(PROFILE, "dbo", [("fa", "technical")], "full", False, "X", ["fa", "en"], False)
            job = json.loads(json.dumps(webapp.JOB))
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual([s["status"] for s in job["steps"]], ["done"] * 4)
        names = [Path(o).name for o in job["outputs"]]
        self.assertIn("dbo_Business_Analysis.fa.md", names)
        self.assertIn("dbo_Business_Analysis.en.md", names)


if __name__ == "__main__":
    unittest.main()
