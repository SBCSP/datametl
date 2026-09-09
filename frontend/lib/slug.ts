/** Client-side tenant slug helper (mirrors backend ``slugify_name``). */

export function slugifyName(name: string, maxLength = 64): string {
  let slug = (name || "")
    .trim()
    .toLowerCase()
    .replace(/_/g, "-")
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
  if (!slug) slug = "workspace";
  slug = slug.slice(0, maxLength).replace(/-+$/g, "");
  return slug || "workspace";
}

export function isValidSlug(slug: string): boolean {
  if (!slug || slug.length > 64) return false;
  if (slug !== slug.toLowerCase()) return false;
  if (slug.startsWith("-") || slug.endsWith("-")) return false;
  return /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug);
}
