# Changelog

## 3.0.0 — 2026-10-25

### Added
- Separate business-analysis document, in Markdown and Word (`<SERVICE>_<date>_business.docx`): modules, table roles, processes, status lifecycles, column meanings, sensitive data, implicit relationships, naming issues, glossary and open questions.
- Offline rules that always run, in Persian and English.
- Optional enrichment with Claude. It sends structure only, stores the key in Windows Credential Manager, and caches its result per snapshot.

### Changed
- The extension is now `atlas-db-docs`. Claude Desktop treats it as a new extension, so remove the previous extension when you install it.
- Bundles contain only the sample profile. Choose your real profiles file in the extension settings.

### Fixed
- Setup no longer fails when a particular profile has been deleted.

## 2.0.0 — 2026-10-25

### Added
- SQL Server support with SQL logins, including `INCLUDE` columns and filtered indexes.
- Delete button for saved databases.

### Fixed
- Second launch failed with an expired-page message. The port is now exclusive, a new launch reopens the running app, and an instance running older code is replaced.

## 1.0.0 — 2026-10-24

### Added
- Read-only Oracle documentation: Markdown, full ERD, snapshot and coverage validation.
- Word (technical and client editions) and draw.io output, with content checks.
- Local data-entry app with passwords in Windows Credential Manager.
- Claude Desktop extension with nine metadata tools.
