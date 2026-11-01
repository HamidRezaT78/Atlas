# Security

Atlas connects to real databases, so what it can and cannot do matters. This page lists those limits.

## What Atlas reads

- Only dictionary and catalog views: Oracle `ALL_*` and `PRODUCT_COMPONENT_VERSION`, SQL Server `sys.*`. It never reads application table rows.
- Every statement is a fixed `SELECT` with bind variables in `oradoc/queries.py` or `oradoc/mssql_queries.py`. No tool accepts SQL text. `tests/test_sql_safety.py` enforces this.
- Schemas are limited to the allowlist of each profile.

## Read-only sessions

- **Oracle:** each session starts with `SET TRANSACTION READ ONLY`, so the database itself refuses writes.
- **SQL Server:** there is no equivalent setting. The session runs in a transaction that is always rolled back and sends only the fixed statements above. Use a login that holds only `VIEW DEFINITION`; the connection test warns when the login can write.

## Secrets

- Database passwords and the Claude API key are stored only in Windows Credential Manager. They are never written to files, logs, documents or responses.
- `config/profiles.toml` holds addresses and usernames but no passwords. It is ignored by git. Do not commit it.
- Release bundles contain only `config/profiles.example.toml`.

## Local app

- The app listens on `127.0.0.1` only. Each launch uses a random token, and requests with another token or `Host` header are refused.
- `logs/instance.json` holds that token while the app runs. Any program running as the same Windows user can read it.

## What leaves your computer

Nothing, unless you turn on **Enrich with Claude**. Then this structure is sent to the Anthropic API: table and column names, data types, keys, relationships, CHECK value lists and recorded comments. Table rows are never sent. Recorded comments are free text, so review them first if they may hold confidential information.

## Generated documents

Documents and snapshots describe your database structure. They are written to `docs/`, which git ignores. Treat them as internal.

## Reporting a vulnerability

Please report it privately through GitHub's **Security → Report a vulnerability** on this repository, not in a public issue.
