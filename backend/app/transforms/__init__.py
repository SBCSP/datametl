"""Per-column / per-row transform pipeline.

Hooked into `LogicalCopyStrategy`. Transforms are declarative (e.g. `{type: "rename_column",
from: "x", to: "y"}`, `{type: "cast", to: "text"}`, `{type: "fk_remap", lookup_table: "users"}`),
not arbitrary code, so they can be persisted next to the mapping and replayed.

Specific transforms anticipated for the Supabase → vanilla Postgres path:
  * `auth.users` → flatten into a destination `users` table (preserving id) so FKs survive.
  * `gen_random_uuid()` defaults → swap for `uuid_generate_v4()` if pgcrypto isn't installed.
  * Strip RLS policies (they're SQL, not data — handled by schema-apply step).
"""
