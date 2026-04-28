-- Supabase-flavored sample source database.
-- Mimics the shape of a real Supabase project enough to exercise the recipe layer:
--   * auth schema with auth.users
--   * storage schema stub
--   * RLS enabled with a policy
--   * gen_random_uuid() default (requires pgcrypto)
--   * a public schema with realistic tables FK'ing to auth.users

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- --- auth schema (Supabase) ---
CREATE SCHEMA IF NOT EXISTS auth;

-- Stubs of the Supabase auth helper functions (real ones are installed by GoTrue).
-- These let RLS policies and views referencing auth.uid() compile in this sample DB.
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$ SELECT NULL::uuid $$;

CREATE OR REPLACE FUNCTION auth.role() RETURNS text
    LANGUAGE sql STABLE
    AS $$ SELECT 'anon'::text $$;

CREATE TABLE auth.users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text UNIQUE NOT NULL,
    encrypted_password text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_sign_in_at timestamptz
);

INSERT INTO auth.users (email) VALUES
    ('alice@example.com'),
    ('bob@example.com'),
    ('carol@example.com');

-- --- storage schema (Supabase) ---
CREATE SCHEMA IF NOT EXISTS storage;

CREATE TABLE storage.buckets (
    id   text PRIMARY KEY,
    name text NOT NULL,
    public boolean DEFAULT false
);

CREATE TABLE storage.objects (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    bucket_id   text REFERENCES storage.buckets(id),
    name        text NOT NULL,
    owner       uuid REFERENCES auth.users(id),
    created_at  timestamptz DEFAULT now()
);

INSERT INTO storage.buckets (id, name, public) VALUES ('avatars', 'avatars', true);

-- --- public schema (user data) ---
CREATE TABLE public.profiles (
    id          uuid PRIMARY KEY REFERENCES auth.users(id),
    username    text UNIQUE NOT NULL,
    full_name   text,
    avatar_url  text,
    bio         text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.posts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id   uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title       varchar(255) NOT NULL,
    body        text,
    metadata    jsonb DEFAULT '{}'::jsonb,
    published   boolean NOT NULL DEFAULT false,
    view_count  bigint NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX posts_author_idx ON public.posts(author_id);
CREATE INDEX posts_published_idx ON public.posts(published) WHERE published;

INSERT INTO public.profiles (id, username, full_name)
SELECT id, split_part(email, '@', 1), initcap(split_part(email, '@', 1))
FROM auth.users;

INSERT INTO public.posts (author_id, title, body, published, view_count)
SELECT u.id, 'Hello from ' || split_part(u.email, '@', 1), 'sample body', true, (random() * 1000)::bigint
FROM auth.users u;

-- --- RLS (Supabase signature feature) ---
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.posts    ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Profiles are viewable by everyone"
    ON public.profiles FOR SELECT
    USING (true);

CREATE POLICY "Users can update own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);

CREATE POLICY "Anyone can read published posts"
    ON public.posts FOR SELECT
    USING (published OR auth.uid() = author_id);

-- A view referencing auth.uid() so the recipe scanner has something to find
CREATE VIEW public.my_posts AS
    SELECT * FROM public.posts WHERE author_id = auth.uid();
