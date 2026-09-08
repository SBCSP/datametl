# DataMETL — launch one-pager

Paste-ready copy for a website or launch post.

---

## Hero

**DataMETL** — Local-first database migration with **Mel**, your read-only DB copilot.

Connect source and destination, compare schemas, map types, stream data, and verify parity — on your laptop or your Docker network. Credentials never leave your environment for SandboxCSP.

---

## Three bullets

1. **Migrate with confidence** — Introspect, compare, map, COPY-stream migrate, and verify (counts + hash samples) for PostgreSQL; Pro adds MySQL and SQL Server.
2. **Mel, approve-to-run** — Ask Mel about schemas and migrations. Live tools are **read-only**; Community requires Approve on every tool; Pro unlocks flexible approval modes. Row samples sent to Anthropic are capped (200 rows); **passwords are not**.
3. **Local-first + one-liner install** — Fernet encryption at rest; offline Ed25519 Pro licenses. No Stripe secrets on your box.

---

## Trust blurb

Credentials stay on the operator machine / Docker network and are Fernet-encrypted at rest. Mel sends prompts and capped tool results to Anthropic using **your** API key — not DB passwords. MCP tools are read-only with audit. Pro licenses verify offline (Ed25519); Stripe runs only on the vendor issuer.

Full detail: in-app `/trust` or `docs/TRUST.md`.

---

## Install

```bash
curl -fsSL https://github.com/sbcsp/datametl/releases/latest/download/install.sh | bash
```

Open http://localhost:3000

---

## Pricing

| Tier | Price | Includes |
|------|-------|----------|
| **Community** | Free | Postgres migrate / introspect / compare / verify; Mel with Approve-always |
| **Pro** | **$79/mo** | Full Mel approval modes + MySQL & SQL Server connectors; offline `dmtl1` license key |

**Buy Pro (Stripe Payment Link — currently sandbox / test mode):**  
https://buy.stripe.com/test_6oU8wQ9cL1Bv3Av9cw7ok00  

After checkout (test card `4242…` in sandbox), paste the issued `dmtl1.…` key in **Settings → License**. Live Payment Link TBD — do not present the `test_` URL as production checkout without a clear test-mode label.
