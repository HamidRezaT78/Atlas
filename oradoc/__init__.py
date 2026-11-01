"""oradoc: the engine of Atlas, read-only schema documentation for Oracle and SQL Server.

Only dictionary/catalog views are queried (ALL_*, sys.*); application table rows are never
read and no arbitrary SQL is accepted.
"""

__version__ = "3.0.0"
