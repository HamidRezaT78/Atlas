"""Local app: profile file editing, input validation, password handling and request guards (offline)."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from oradoc import webapp
from oradoc.config import load_config

BASE = """# comment kept
default_profile = "sales_db"

[profiles.sales_db]
dsn = "10.0.0.1:1521/SALES_DB"
username = "atlas_reader"
keyring_service = "Oradoc_sales_db"
allowed_schemas = ["APP_OWNER"]
default_schema = "APP_OWNER"
call_timeout_ms = 10000
"""


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, password):
        self.store[(service, user)] = password

    def delete_password(self, service, user):
        if (service, user) not in self.store:
            raise RuntimeError("PasswordDeleteError")
        del self.store[(service, user)]


class ProfileFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.cfg = self.dir / "profiles.toml"
        self.cfg.write_text(BASE, encoding="utf-8")
        self.kr = FakeKeyring()
        self.patches = [mock.patch.object(webapp, "CONFIG_PATH", self.cfg),
                        mock.patch.object(webapp, "keyring", self.kr)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def body(self, **kw):
        b = {"name": "hr_prod", "host": "db2.local", "port": 1522, "service": "HRPROD",
             "username": "atlas_reader", "schemas": ["hr", "PAYROLL"], "password": "s3cret"}
        b.update(kw)
        return b

    def test_new_profile_appended_and_password_in_keyring_only(self):
        webapp.save_profile(self.body())
        text = self.cfg.read_text(encoding="utf-8")
        self.assertIn("# comment kept", text)
        self.assertNotIn("s3cret", text)
        p = load_config(self.cfg)["profiles"]["hr_prod"]
        self.assertEqual(p.dsn, "db2.local:1522/HRPROD")
        self.assertEqual(p.allowed_schemas, ("HR", "PAYROLL"))
        self.assertEqual(self.kr.store[("Oradoc_hr_prod", "atlas_reader")], "s3cret")
        self.assertTrue(list((self.dir / "_backup").glob("profiles_*.toml")))

    def test_existing_profile_needs_replace_and_keeps_keyring_service(self):
        with self.assertRaises(webapp.UserError):
            webapp.save_profile(self.body(name="sales_db"))
        self.kr.store[("Oradoc_sales_db", "atlas_reader")] = "old"
        webapp.save_profile(self.body(name="sales_db", replace=True, password="", schemas=["APP_OWNER", "X"]))
        profiles = load_config(self.cfg)["profiles"]
        self.assertEqual(profiles["sales_db"].keyring_service, "Oradoc_sales_db")
        self.assertEqual(profiles["sales_db"].allowed_schemas, ("APP_OWNER", "X"))
        self.assertEqual(self.kr.store[("Oradoc_sales_db", "atlas_reader")], "old")
        self.assertEqual(self.cfg.read_text(encoding="utf-8").count("[profiles.sales_db]"), 1)

    def test_new_profile_without_password_rejected(self):
        with self.assertRaises(webapp.UserError):
            webapp.save_profile(self.body(password=""))
        self.assertNotIn("hr_prod", self.cfg.read_text(encoding="utf-8"))

    def test_bad_inputs_rejected_before_writing(self):
        for bad in ({"host": "a b"}, {"port": 0}, {"service": "x;y"}, {"username": "1x"},
                    {"name": "bad name"}, {"schemas": []}, {"schemas": ["DROP TABLE"]}):
            with self.subTest(bad=bad), self.assertRaises(webapp.UserError):
                webapp.save_profile(self.body(**bad))
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), BASE)

    def test_delete_profile_removes_block_and_password(self):
        webapp.save_profile(self.body())
        out = webapp.delete_profile({"name": "hr_prod"})
        self.assertEqual((out["password_deleted"], out["password_shared"]), (True, False))
        text = self.cfg.read_text(encoding="utf-8")
        self.assertNotIn("hr_prod", text)
        self.assertIn("# comment kept", text)
        self.assertEqual(list(load_config(self.cfg)["profiles"]), ["sales_db"])
        self.assertNotIn(("Oradoc_hr_prod", "atlas_reader"), self.kr.store)
        self.assertGreaterEqual(len(list((self.dir / "_backup").glob("profiles_*.toml"))), 2)

    def test_delete_default_profile_moves_default(self):
        webapp.save_profile(self.body())
        webapp.delete_profile({"name": "sales_db", "delete_password": False})
        cfg = load_config(self.cfg)
        self.assertEqual((cfg["default_profile"], list(cfg["profiles"])), ("hr_prod", ["hr_prod"]))
        webapp.delete_profile({"name": "hr_prod"})
        cfg = load_config(self.cfg)
        self.assertEqual((cfg["default_profile"], cfg["profiles"]), (None, {}))
        self.assertEqual(webapp.list_profiles()["profiles"], [])

    def test_delete_keeps_password_shared_with_another_profile(self):
        self.kr.store[("Oradoc_sales_db", "atlas_reader")] = "pw"
        text = self.cfg.read_text(encoding="utf-8")
        self.cfg.write_text(text + text.split("default_profile = \"sales_db\"\n", 1)[1]
                            .replace("[profiles.sales_db]", "[profiles.sales_copy]"), encoding="utf-8")
        out = webapp.delete_profile({"name": "sales_copy"})
        self.assertEqual((out["password_deleted"], out["password_shared"]), (False, True))
        self.assertEqual(self.kr.store[("Oradoc_sales_db", "atlas_reader")], "pw")

    def test_delete_refused_for_unknown_or_busy_profile(self):
        with self.assertRaises(webapp.UserError):
            webapp.delete_profile({"name": "nope"})
        with mock.patch.dict(webapp.JOB, {"state": "running", "profile": "sales_db"}):
            with self.assertRaises(webapp.UserError):
                webapp.delete_profile({"name": "sales_db"})
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), BASE)

    def test_list_profiles_never_returns_secrets(self):
        self.kr.store[("Oradoc_sales_db", "atlas_reader")] = "pw"
        out = webapp.list_profiles()
        self.assertEqual(out["profiles"][0]["host"], "10.0.0.1")
        self.assertTrue(out["profiles"][0]["has_password"])
        self.assertNotIn("pw", json.dumps(out).replace("has_password", ""))


class HttpGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = webapp.make_server(port=0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", webapp.APP.port, timeout=5)
        h = {"Host": f"127.0.0.1:{webapp.APP.port}"}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        return r.status, r.read()

    def test_page_requires_token_and_injects_it(self):
        self.assertEqual(self.request("GET", "/")[0], 403)
        status, data = self.request("GET", f"/?t={webapp.APP.token}")
        self.assertEqual(status, 200)
        self.assertIn(webapp.APP.token.encode(), data)
        self.assertNotIn(b"__ORADOC_TOKEN__", data)

    def test_api_requires_token_header(self):
        self.assertEqual(self.request("GET", "/api/job")[0], 403)
        self.assertEqual(self.request("GET", "/api/job", {"X-Oradoc-Token": "wrong"})[0], 403)
        self.assertEqual(self.request("GET", "/api/job", {"X-Oradoc-Token": webapp.APP.token})[0], 200)

    def test_foreign_host_rejected(self):
        status, _ = self.request("GET", "/api/job", {"Host": "evil.example:80", "X-Oradoc-Token": webapp.APP.token})
        self.assertEqual(status, 403)

    def test_validation_error_is_400_with_message(self):
        status, data = self.request("POST", "/api/test", {"X-Oradoc-Token": webapp.APP.token,
                                                           "Content-Type": "application/json"},
                                    json.dumps({"host": "bad host"}))
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(data))

    def test_port_cannot_be_bound_twice(self):
        # A second instance on the same port would receive none of the requests (old token -> 403).
        with self.assertRaises(OSError):
            webapp.AtlasServer(("127.0.0.1", webapp.APP.port), webapp.Handler)

    def test_second_launch_reuses_running_instance(self):
        path = Path(tempfile.mkdtemp()) / "instance.json"
        with mock.patch.object(webapp, "INSTANCE_PATH", path):
            self.assertIsNone(webapp.running_instance())  # no file
            webapp._write_instance()
            self.assertEqual(webapp.running_instance(), webapp.app_url(webapp.APP.port, webapp.APP.token))
            opened = []
            with mock.patch.object(webapp.webbrowser, "open", opened.append), \
                    mock.patch.object(webapp, "make_server", side_effect=AssertionError("must not start a server")):
                webapp.main()
            self.assertEqual(opened, [webapp.app_url(webapp.APP.port, webapp.APP.token)])
            path.write_text(json.dumps({"port": webapp.APP.port, "token": "stale"}), encoding="utf-8")
            self.assertIsNone(webapp.running_instance())  # stale token: start a new one
            webapp._remove_instance()
            self.assertTrue(path.exists())  # someone else's record is left alone

    def test_older_instance_is_not_reused_and_asked_to_quit(self):
        path = Path(tempfile.mkdtemp()) / "instance.json"
        path.write_text(json.dumps({"port": webapp.APP.port, "token": webapp.APP.token, "version": "old"}),
                        encoding="utf-8")
        calls = []
        real_call = webapp._call

        def spy(port, token, method, url):
            calls.append((method, url))
            return 200 if url == "/api/job" else real_call(port, token, "GET", "/api/job")  # never really quit

        with mock.patch.object(webapp, "INSTANCE_PATH", path), mock.patch.object(webapp, "_call", spy):
            self.assertIsNone(webapp.running_instance())
        self.assertEqual(calls, [("GET", "/api/job"), ("POST", "/api/quit")])

    def test_quit_refused_while_job_runs(self):
        with mock.patch.dict(webapp.JOB, {"state": "running"}):
            with self.assertRaises(webapp.UserError):
                webapp.quit_app({})

    def test_open_folder_outside_docs_refused(self):
        with self.assertRaises(webapp.UserError):
            webapp.open_folder("C:\\Windows")


if __name__ == "__main__":
    unittest.main()
