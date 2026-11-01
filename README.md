# Atlas

Read-only documentation for Oracle and SQL Server databases, on Windows. Enter a connection in a local page and get technical and client documents, a full ERD and a business analysis, in Persian or English.

[فارسی](#فارسی)

## Features

- **Technical and client documents:** Markdown and Word, with coverage validated so every table and relationship is present.
- **ERD:** Mermaid, plus an editable draw.io file.
- **Structural analysis:** missing keys, unindexed foreign keys, duplicate indexes and similar findings, each with its evidence.
- **Business analysis:** modules, table roles, processes, column meanings, sensitive data, implicit relationships and naming issues. It runs offline, with optional enrichment by Claude.
- **Claude Desktop extension:** lets Claude read the same metadata in a chat.

Atlas reads only dictionary and catalog views, never table rows. See [SECURITY.md](SECURITY.md).

## Requirements

- Windows 10 or 11, 64-bit
- Python 3.11 or newer, with **Add python.exe to PATH** ticked during installation
- A short install path, at most 100 characters, such as `C:\Atlas`. Windows limits file paths to 260 characters
- Network access to the database
- For Word output: Microsoft Word, and Chrome or Edge
- For SQL Server: SQL Server Authentication and TCP/IP enabled. No ODBC driver is needed

## Quick start

Download `Atlas-Tools-<version>.zip` from [Releases](../../releases). It installs without internet. Or clone the repository; `Setup.cmd` then downloads the dependencies:

```powershell
git clone https://github.com/HamidRezaT78/Atlas.git
cd Atlas
.\Setup.cmd
.\Atlas.cmd
```

In the page that opens:

1. Choose Oracle or SQL Server, enter the connection and click the connection test.
2. Select the schemas and save. The password goes to Windows Credential Manager.
3. Choose languages and editions, and start. Results are written to `docs\`.

## Read-only database user

Oracle sessions are read-only by the database itself. SQL Server has no such setting, so give Atlas a login that can only see the structure:

```sql
CREATE LOGIN atlas_reader WITH PASSWORD = '<strong password>';
USE [YourDatabase];
CREATE USER atlas_reader FOR LOGIN atlas_reader;
GRANT VIEW DEFINITION TO atlas_reader;
```

## Business analysis with Claude (optional)

Without a key, the analysis is built offline from rules. To get richer descriptions, save a [Claude API key](https://console.anthropic.com) in the page and turn on **Enrich with Claude**. Atlas sends only structure, never data. It uses `claude-opus-5-5` and shows the actual cost in the job log.

## Claude Desktop extension

1. Download `atlas-db-docs-<version>.mcpb` from Releases.
2. In Claude Desktop, open **Settings → Extensions** and install the file.
3. Set **Profiles file** to `config\profiles.toml` in your Atlas folder, then restart Claude Desktop.

Claude Desktop installs the extension's dependencies on first run, which needs internet.

## Command line

```powershell
.\.venv\Scripts\python.exe -m oradoc profiles
.\.venv\Scripts\python.exe -m oradoc generate --profile <profile> --schema <SCHEMA> --lang fa --detail full
.\.venv\Scripts\python.exe -m oradoc business --from-snapshot <snapshot.json> --lang fa
.\.venv\Scripts\python.exe tools\publish\publish.py --run <run folder> --service <NAME> --profile <profile>
```

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
.\.venv\Scripts\python.exe tools\build_release.py
```

Tests run offline, with no database. `build_release.py` writes the Release assets to `dist\`.

| Path | Purpose |
|---|---|
| `oradoc/` | Engine: queries, collector, analysis, rendering, business analysis, local app |
| `ui/oradoc_app.html` | Local app page |
| `tools/publish/` | Word and draw.io output |
| `mcpb-src/` | Claude Desktop extension |
| `config/profiles.example.toml` | Sample profiles |

## License

[MIT](LICENSE). Third-party components are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

<div dir="rtl">

## فارسی

اطلس برای دیتابیس‌های Oracle و SQL Server، روی ویندوز، مستند می‌سازد و فقط ساختار را می‌خواند، نه داده‌ها را. اطلاعات اتصال را در یک صفحه محلی وارد می‌کنید و خروجی می‌گیرید:

- مستند فنی و مستند کارفرما، به‌صورت Markdown و Word
- نمودار ERD قابل ویرایش در draw.io
- تحلیل بیزنسی، به‌صورت مستند جداگانه

### راه‌اندازی

1. Python نسخه 3.11 یا جدیدتر را نصب کنید و هنگام نصب گزینه **Add python.exe to PATH** را تیک بزنید.
2. فایل `Atlas-Tools-<version>.zip` را از بخش Releases بگیرید و باز کنید. این نسخه بدون اینترنت نصب می‌شود.
3. روی `Setup.cmd` و بعد روی `Atlas.lnk` دوبار کلیک کنید.

مسیر پوشه باید کوتاه باشد (حداکثر ۱۰۰ نویسه)، مثلاً `C:\Atlas`.

رمز دیتابیس فقط در Windows Credential Manager ذخیره می‌شود. برای ساخت Word به Microsoft Word و Chrome یا Edge نیاز دارید.

تحلیل بیزنسی بدون هوش مصنوعی و به‌صورت آفلاین ساخته می‌شود. اگر غنی‌سازی با Claude را روشن کنید، فقط ساختار دیتابیس به Anthropic ارسال می‌شود و داده‌ها ارسال نمی‌شوند. جزئیات امنیتی در [SECURITY.md](SECURITY.md) آمده است.

</div>
