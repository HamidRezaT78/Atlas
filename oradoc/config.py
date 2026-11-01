"""Connection profiles and the schema allowlist. Passwords never live here.

engine = "oracle" (default) or "sqlserver". For SQL Server, dsn is host[\\instance]:port/database and
schema/table names keep their case (comparisons are case-insensitive, like the default collation)."""
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,127}")
MSSQL_NAME_RE = re.compile(r"[\w@#$][\w@#$ .\-]{0,127}")
ENGINES = ("oracle", "sqlserver")
PROFILE_RE = re.compile(r"[A-Za-z0-9_\-]{1,64}")
PACKAGE_DIR = Path(__file__).resolve().parent
FORBIDDEN_KEYS = {"password", "passwd", "pwd", "secret", "token"}


@dataclass(frozen=True)
class Profile:
    name: str
    dsn: str
    username: str
    keyring_service: str
    allowed_schemas: tuple
    default_schema: str
    call_timeout_ms: int = 10000
    engine: str = "oracle"

    def check_schema(self, schema=None):
        """Return the schema as written in the allowlist if it is on this profile's allowlist."""
        s = (schema or self.default_schema or "").strip()
        if self.engine == "sqlserver":
            match = [a for a in self.allowed_schemas if a.casefold() == s.casefold()]
            if MSSQL_NAME_RE.fullmatch(s) and match:
                return match[0]
        elif NAME_RE.fullmatch(s.upper()) and s.upper() in self.allowed_schemas:
            return s.upper()
        raise ValueError(f"Schema {s!r} is not in the allowlist of profile {self.name!r}.")


def check_object_name(name, engine="oracle"):
    """Validate an object name before it is used as a bind value (Oracle: upper-cased)."""
    if not isinstance(name, str):
        raise ValueError("Invalid object name.")
    if engine == "sqlserver":
        if not MSSQL_NAME_RE.fullmatch(name.strip()):
            raise ValueError("Invalid object name.")
        return name.strip()
    if not NAME_RE.fullmatch(name.strip()):
        raise ValueError("Invalid object name.")
    return name.strip().upper()


def config_candidates(extra=None):
    paths = []
    env = os.environ.get("ORADOC_CONFIG", "").strip()
    if env and "${" not in env:  # an unset extension setting may arrive empty or unsubstituted
        paths.append(Path(env))
    paths.extend(Path(p) for p in (extra or []))
    paths.append(PACKAGE_DIR.parent / "config" / "profiles.toml")  # project checkout
    paths.append(PACKAGE_DIR.parent / "profiles.toml")  # inside the MCP bundle
    return paths


def find_config(path=None, extra=None):
    if path:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Profile config not found: {p}")
        return p
    for p in config_candidates(extra):
        if p.is_file():
            return p
    raise FileNotFoundError("No profiles.toml found (set ORADOC_CONFIG or create config/profiles.toml).")


def load_config(path=None, extra=None):
    p = find_config(path, extra)
    with open(p, "rb") as f:
        data = tomllib.load(f)
    profiles = {}
    for name, raw in (data.get("profiles") or {}).items():
        if not PROFILE_RE.fullmatch(name):
            raise ValueError(f"Invalid profile name {name!r}.")
        bad = FORBIDDEN_KEYS & {k.lower() for k in raw}
        if bad:
            raise ValueError(f"Profile {name!r} contains forbidden key(s) {sorted(bad)}; "
                             "passwords belong in Windows Credential Manager.")
        engine = raw.get("engine", "oracle")
        if engine not in ENGINES:
            raise ValueError(f"Profile {name!r}: engine must be one of {ENGINES}.")
        schemas = tuple(check_object_name(s, engine) for s in raw.get("allowed_schemas", []))
        if not schemas:
            raise ValueError(f"Profile {name!r} has an empty allowed_schemas list.")
        default_schema = check_object_name(raw.get("default_schema", schemas[0]), engine)
        if default_schema not in schemas:
            raise ValueError(f"Profile {name!r}: default_schema is not in allowed_schemas.")
        for key in ("dsn", "username", "keyring_service"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise ValueError(f"Profile {name!r} is missing {key!r}.")
        profiles[name] = Profile(
            name=name,
            dsn=raw["dsn"].strip(),
            username=raw["username"].strip(),
            keyring_service=raw["keyring_service"].strip(),
            allowed_schemas=schemas,
            default_schema=default_schema,
            call_timeout_ms=int(raw.get("call_timeout_ms", 10000)),
            engine=engine,
        )
    return {"path": p, "default_profile": data.get("default_profile"), "profiles": profiles}


def get_profile(name=None, path=None, extra=None):
    cfg = load_config(path, extra)
    name = name or os.environ.get("ORADOC_PROFILE") or cfg["default_profile"]
    if not name or name not in cfg["profiles"]:
        raise ValueError(f"Unknown profile {name!r}. Available: {sorted(cfg['profiles'])}")
    return cfg["profiles"][name]
