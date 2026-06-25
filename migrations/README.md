# Migrations

Numbered, idempotent SQL migration files applied automatically on bot startup by
`db._apply_migrations()` (called from `db._migrate()`), in filename order, and
tracked in the `schema_migrations` table so each runs at most once.

## Conventions

- Name files `NNN_short_description.sql` (e.g. `001_add_bet_indexes.sql`).
- Use a zero-padded, monotonically increasing prefix so lexical sort = apply order.
- Write idempotent DDL where practical (`IF NOT EXISTS`, `IF EXISTS`) so a file is
  safe even if a column was already added by the legacy baseline ALTERs in
  `db._migrate()` or by `init.sql`.
- One logical change per file. Each file is applied inside its own transaction.

## Relationship to init.sql

`init.sql` is the **complete current schema** for fresh installs and tests. The
baseline `ALTER ... IF NOT EXISTS` calls in `db._migrate()` exist only to bring an
older live database up to that schema. New schema changes from here on should be
added as migration files in this directory rather than appended to `_migrate()`.
