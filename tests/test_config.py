import tempfile
import unittest
from pathlib import Path

from oradoc.config import check_object_name, get_profile, load_config

GOOD = """
default_profile = "p1"
[profiles.p1]
dsn = "host:1521/SVC"
username = "READER"
keyring_service = "Svc"
allowed_schemas = ["APP", "app_owner"]
default_schema = "APP"
"""


def write(text):
    d = tempfile.mkdtemp()
    p = Path(d) / "profiles.toml"
    p.write_text(text, encoding="utf-8")
    return p


class ConfigTest(unittest.TestCase):
    def test_loads_profile_and_allowlist(self):
        prof = get_profile(path=write(GOOD))
        self.assertEqual(prof.allowed_schemas, ("APP", "APP_OWNER"))
        self.assertEqual(prof.check_schema(None), "APP")
        self.assertEqual(prof.check_schema("app_owner"), "APP_OWNER")
        for bad in ("SYS", "APP; DROP", "A" * 200):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                prof.check_schema(bad)

    def test_rejects_password_keys(self):
        for key in ("password", "PWD", "secret"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_config(write(GOOD + f'{key} = "x"\n'))

    def test_rejects_default_schema_outside_allowlist(self):
        with self.assertRaises(ValueError):
            load_config(write(GOOD.replace('default_schema = "APP"', 'default_schema = "OTHER"')))

    def test_object_names(self):
        self.assertEqual(check_object_name("users"), "USERS")
        for bad in ("1ABC", "A B", "A;B", "A'--", None, ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                check_object_name(bad)

    def test_project_config_has_no_secrets(self):
        # Whatever profiles this installation holds (users add and delete them), the file must load:
        # load_config rejects password-like keys.
        path = Path(__file__).resolve().parent.parent / "config" / "profiles.toml"
        if not path.is_file():
            self.skipTest("no profiles.toml in this installation")
        for p in load_config(path)["profiles"].values():
            self.assertTrue(p.allowed_schemas)


class ConfigEnvTest(unittest.TestCase):
    def test_empty_or_unsubstituted_env_is_ignored(self):
        from unittest import mock
        from oradoc.config import config_candidates
        for value in ("", "  ", "${user_config.profiles_file}"):
            with self.subTest(value=value), mock.patch.dict("os.environ", {"ORADOC_CONFIG": value}):
                self.assertFalse(any("${" in str(p) or str(p) in ("", ".") for p in config_candidates()))


if __name__ == "__main__":
    unittest.main()
