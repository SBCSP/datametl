"""Supabase-aware analysis pass.

Runs over a normalized Schema and emits Warnings about Supabase-specific things that
matter when migrating to vanilla Postgres:

  * Presence of Supabase-managed schemas (auth, storage, realtime, _supabase, vault, pgsodium, extensions)
  * RLS policies (vanilla Postgres can keep them, but the destination might not want them)
  * `gen_random_uuid()` defaults (require pgcrypto on the destination)
  * View / policy expressions that reference auth.uid() / auth.role() / auth.jwt()
  * FKs from public tables into auth.users (a destination without GoTrue won't have these targets)
  * Supabase-only extensions (pgsodium, vault) on the source
"""
from __future__ import annotations

import re

from app.introspection.normalized import Schema, Warning

# Schemas that Supabase manages. Detection alone isn't an error — the recipe just surfaces
# them so the user can decide what to do (skip, migrate verbatim, transform).
SUPABASE_SCHEMAS = frozenset(
    {"auth", "storage", "realtime", "_supabase", "vault", "pgsodium", "extensions", "graphql", "graphql_public"}
)
SUPABASE_ONLY_EXTENSIONS = frozenset({"pgsodium", "vault", "supabase_vault"})

_AUTH_HELPER_RE = re.compile(r"\bauth\.(uid|role|jwt|email)\s*\(", re.IGNORECASE)
_GEN_UUID_RE = re.compile(r"\bgen_random_uuid\s*\(", re.IGNORECASE)


def analyze(schema: Schema) -> list[Warning]:
    warnings: list[Warning] = []

    present_schemas = {t.schema_ for t in schema.tables} | {v.schema_ for v in schema.views}
    supabase_present = present_schemas & SUPABASE_SCHEMAS
    if supabase_present:
        warnings.append(
            Warning(
                code="supabase.schemas_present",
                severity="info",
                message=(
                    f"Supabase-managed schemas detected: {sorted(supabase_present)}. "
                    "Decide per schema whether to skip, migrate verbatim, or transform."
                ),
                target=None,
            )
        )

    for ext in schema.extensions:
        if ext in SUPABASE_ONLY_EXTENSIONS:
            warnings.append(
                Warning(
                    code="supabase.extension_only_in_supabase",
                    severity="warning",
                    message=f"Extension `{ext}` is Supabase-specific; vanilla Postgres won't have it.",
                    target=f"extension:{ext}",
                )
            )

    if "pgcrypto" not in schema.extensions:
        # Source doesn't have pgcrypto installed — but it might still rely on gen_random_uuid()
        # if PG14+ (which exposes it natively). Either way, surface defaults using it.
        pass

    for table in schema.tables:
        for col in table.columns:
            if col.default and _GEN_UUID_RE.search(col.default):
                warnings.append(
                    Warning(
                        code="supabase.gen_random_uuid_default",
                        severity="info",
                        message=(
                            f"Column `{table.qualified_name}.{col.name}` defaults to gen_random_uuid(). "
                            "Ensure pgcrypto is installed on the destination, or use Postgres 14+ where it is built-in."
                        ),
                        target=f"column:{table.qualified_name}.{col.name}",
                    )
                )

            if col.foreign_key and col.foreign_key.schema_ == "auth" and col.foreign_key.table == "users":
                warnings.append(
                    Warning(
                        code="supabase.fk_to_auth_users",
                        severity="warning",
                        message=(
                            f"Column `{table.qualified_name}.{col.name}` references auth.users. "
                            "If the destination has no Supabase auth, the FK will be unsatisfiable — "
                            "either migrate auth.users, flatten into a destination users table, "
                            "or drop the constraint."
                        ),
                        target=f"column:{table.qualified_name}.{col.name}",
                    )
                )

        if table.rls_enabled:
            warnings.append(
                Warning(
                    code="supabase.rls_enabled",
                    severity="info",
                    message=(
                        f"RLS is enabled on `{table.qualified_name}`. "
                        "Decide whether to migrate policies as-is or strip them on the destination."
                    ),
                    target=f"table:{table.qualified_name}",
                )
            )

    for policy in schema.rls_policies:
        for expr in (policy.using_expr or "", policy.with_check_expr or ""):
            if _AUTH_HELPER_RE.search(expr):
                warnings.append(
                    Warning(
                        code="supabase.policy_uses_auth_helper",
                        severity="warning",
                        message=(
                            f"RLS policy `{policy.name}` on `{policy.schema_}.{policy.table}` "
                            "calls auth.uid() / auth.role() / auth.jwt(). "
                            "These functions are provided by Supabase GoTrue — the destination needs equivalents."
                        ),
                        target=f"policy:{policy.schema_}.{policy.table}.{policy.name}",
                    )
                )
                break

    for view in schema.views:
        if _AUTH_HELPER_RE.search(view.definition):
            warnings.append(
                Warning(
                    code="supabase.view_uses_auth_helper",
                    severity="warning",
                    message=(
                        f"View `{view.schema_}.{view.name}` references Supabase auth helpers. "
                        "Replace or stub them on the destination."
                    ),
                    target=f"view:{view.schema_}.{view.name}",
                )
            )

    return warnings
