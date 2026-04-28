/** Plain-English guidance for each warning code, written from the migration-planning angle.
 * Add new entries when the backend introduces new warning codes (see backend/app/recipes/). */
export const WARNING_GUIDANCE: Record<string, string> = {
  "supabase.schemas_present":
    "Supabase manages these schemas through its own services (GoTrue / Storage / Realtime / Vault). Decide per schema whether to migrate verbatim, flatten, or skip — vanilla Postgres has no equivalent services to back them.",
  "supabase.extension_only_in_supabase":
    "This extension is part of Supabase's bundled stack. Vanilla Postgres won't have it. Either remove dependent code on the destination or arrange to install an equivalent extension.",
  "supabase.gen_random_uuid_default":
    "Column default uses gen_random_uuid(). On Postgres 13+ this is built-in; on older versions it requires the pgcrypto extension. Verify the destination has one of those, or change the default.",
  "supabase.fk_to_auth_users":
    "Foreign key targets auth.users. If the destination has no auth schema (no GoTrue), the FK will be unsatisfiable after migration. Options: (1) migrate auth.users verbatim, (2) flatten user data into a destination users table, (3) drop the FK and keep the user_id as a free column.",
  "supabase.rls_enabled":
    "Row Level Security is on. If you migrate table DDL with policies attached, the destination must have equivalent auth context or the policies will block all access. Most destination Postgres setups want RLS stripped.",
  "supabase.policy_uses_auth_helper":
    "Policy calls auth.uid() / auth.role() / auth.jwt(). Those helpers are provided by Supabase's GoTrue. The destination needs equivalents (often custom SQL functions returning NULL), or the policy needs to be rewritten / dropped.",
  "supabase.view_uses_auth_helper":
    "View definition references Supabase auth helpers. Replace or stub them on the destination so the view compiles.",
};

export function explain(code: string): string | null {
  return WARNING_GUIDANCE[code] ?? null;
}
