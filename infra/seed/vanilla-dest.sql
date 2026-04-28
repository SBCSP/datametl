-- Vanilla Postgres destination — intentionally mostly-empty so a comparison
-- with the Supabase-flavored source produces interesting drift.

-- One table that exists in both, with a column drift example:
--   * source has `metadata jsonb` and `view_count bigint`; this destination doesn't have them
--   * source has `created_at timestamptz`; here we use `created_at timestamp` (no tz) on purpose
CREATE TABLE public.posts (
    id          uuid PRIMARY KEY,
    author_id   uuid NOT NULL,
    title       varchar(255) NOT NULL,
    body        text,
    published   boolean NOT NULL DEFAULT false,
    created_at  timestamp NOT NULL DEFAULT now()
);

-- The destination intentionally does NOT have:
--   * public.profiles      (table only in source)
--   * auth schema          (Supabase-specific)
--   * storage schema       (Supabase-specific)
--   * any RLS policies
--   * pgcrypto extension   (so gen_random_uuid() defaults need attention)
