# Embedding and identity: client integration guide (A4 model-quality-gate)

This service ships two pieces: a FastAPI backend (the eval / red-team / promotion-gate API)
and a Next.js UI (`ui/`). This guide explains how a client embeds the UI into their existing
web app (or runs it standalone), and how the backend enforces per-user identity server-side
instead of trusting a client-supplied `actor`.

The scope here is the same-origin (reverse-proxy) embed, the standalone-behind-IAP deploy,
and local-dev-no-auth. Cross-origin embedding (a loader plus postMessage plus a bearer-token
handoff), per-hop token exchange (OBO), and a self-issued session cookie ("launch in new
tab") are further hardening layers: see the "Further layers" note at the end.

## 1. The identity contract

The backend never trusts a client-asserted identity. Every state-changing and query route
depends on a server-verified `Principal`:

- The request body carries **no `actor` field**. If a caller sends one, it is dropped by the
  Pydantic schema and ignored.
- A FastAPI dependency (`api/security.py:get_principal`) builds a `RequestContext` from the
  inbound headers and calls the active profile's `IdentityPort` adapter. The resolved
  `Principal.subject` becomes the audit actor recorded on every eval / red-team / gate event.
- If no verified principal can be resolved, the request is a **401**.

`IdentityPort` is a normal hexagon port (`ports/identity.py`), so the identity mechanism is a
one-line profile switch, exactly like every other port:

| Profile           | Adapter                        | How identity is verified                                  |
| ----------------- | ------------------------------ | --------------------------------------------------------- |
| `local`           | `LocalPersonaIdentityAdapter`  | Seeded dev persona chosen by the `X-Dev-Persona` header   |
| `gcp` / `platform`| `IapIdentityAdapter`           | Cloud IAP signed assertion (`x-goog-iap-jwt-assertion`)   |
| `onprem`          | `OnPremIdentityAdapter`        | Placeholder: verify your enterprise IdP (OIDC/SAML) here  |

The client's job is only to make sure the request reaches the backend with whatever the
active profile needs (a persona header in local mode, or a request path that traverses Cloud
IAP in secure mode). The client never asserts who the user is.

## 2. The four seeded personas (local only)

Local mode runs with no IdP, so demos and tests stay offline. `GET /v1/personas` lists the
seeded personas; the UI renders a "Demo identity" picker from them and sends the chosen id as
`X-Dev-Persona`. There is a cross-tenant persona so per-user and per-tenant authorization is
demoable offline.

| Persona id     | Subject                        | Tenant      | Entitlement groups                                  |
| -------------- | ------------------------------ | ----------- | --------------------------------------------------- |
| `analyst`      | `demo.analyst@bank.example`    | `demo-bank` | `mrm-analyst`, `model-risk`                         |
| `approver`     | `demo.approver@bank.example`   | `demo-bank` | `mrm-analyst`, `model-risk`, `mrm-approver`         |
| `auditor`      | `demo.auditor@bank.example`    | `demo-bank` | `audit`                                             |
| `other-tenant` | `user@other-tenant.example`    | `other-bank`| `mrm-analyst`                                       |

The first persona (`analyst`) is the default when no header is sent. An unknown persona id is
a 401 (the adapter raises `IdentityError`). Secure profiles return an empty persona list, so
the picker does not render outside local mode.

## 3. Deployment shapes

### Shape A: embedded, same-origin reverse proxy (recommended)

Serve the agent under the parent app's origin, for example `portal.client.com/agent/*`, so
the iframe is first-party. No third-party-cookie problem, no CORS.

### Shape B: standalone behind Cloud IAP

Deploy the UI and API on their own host (for example `a4.client.com`) fronted by Cloud IAP.
IAP authenticates the user and injects the signed assertion the backend verifies. Use this
when there is no host app to embed into.

### Shape C: local dev, no auth

Run everything on a laptop with `AI_QUALITY_PROFILE=local`. Identity comes from the persona
picker. No IdP, no emulator, no API key.

## 4. Run locally (Shape C)

```bash
# Backend (repo root)
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
AI_QUALITY_PROFILE=local make run-api    # uvicorn on :8084

# UI (in ./ui)
cp .env.local.example .env.local         # NEXT_PUBLIC_API_BASE=http://localhost:8084
npm install && npm run dev               # Next.js dev server on :3000
```

Open the UI, pick a persona in the "Demo identity" panel, and run the gate. The audit event
records the persona subject as the actor.

## 5. Secure deploy behind Cloud IAP (Shape B)

Cloud IAP is configured on the GCP service (an HTTPS load balancer plus IAP, or Cloud Run
with IAP), so the app writes almost no auth code. Set the profile and the expected audience:

```bash
AI_QUALITY_PROFILE=gcp
# The IAP-protected resource. For an HTTPS LB + IAP:
#   /projects/<PROJECT_NUMBER>/global/backendServices/<BACKEND_SERVICE_ID>
# For Cloud Run / App Engine IAP:
#   /projects/<PROJECT_NUMBER>/apps/<APP_ID>
AI_QUALITY_IAP_AUDIENCE=/projects/123456789/global/backendServices/9876543210
```

The `IapIdentityAdapter` verifies the assertion signature, audience, issuer, and expiry, then
derives the subject from the `email` (or `sub`) claim and the tenant from the hosted-domain
(`hd`) claim. The assertion is never logged. To federate an external client IdP into Google,
use Workforce Identity Federation at the IAP edge: the app code does not change.

## 6. Embed via same-origin reverse proxy (Shape A)

### 6a. Reverse-proxy `/agent/*` to the agent service (nginx)

```nginx
# On https://portal.client.com
location /agent/ {
    proxy_pass http://a4-ui:3000/agent/;          # the Next.js UI, mounted at /agent
    proxy_set_header Host $host;
}
location /agent/api/ {
    proxy_pass http://a4-api:8084/;               # the FastAPI backend
    proxy_set_header Host $host;
    # In secure mode this hop is behind Cloud IAP; the assertion header is forwarded here.
}
```

The UI's API calls resolve same-origin, so set `NEXT_PUBLIC_API_BASE=/agent/api` at build
time.

### 6b. Mount the UI under the sub-path and hide its chrome

```bash
# Build-time environment for the agent UI:
NEXT_PUBLIC_BASE_PATH=/agent          # basePath + assetPrefix (see next.config.mjs)
NEXT_PUBLIC_EMBED=1                   # drop the app header/footer; the host owns the chrome
NEXT_PUBLIC_API_BASE=/agent/api       # same-origin API path
```

### 6c. The iframe tag (host page)

```html
<iframe
  src="https://portal.client.com/agent/"
  title="AI Quality and Model-Risk"
  style="width: 100%; height: 800px; border: 0;"
  sandbox="allow-scripts allow-same-origin allow-forms"
></iframe>
```

### 6d. Allow the parent origin to frame the UI

The backend emits a `Content-Security-Policy: frame-ancestors` header from
`AI_QUALITY_FRAME_ANCESTORS` (default `'self'`). List the parent origins allowed to iframe
the UI; multiple parents are space-separated per the CSP grammar:

```bash
export AI_QUALITY_FRAME_ANCESTORS="https://portal.client.com https://admin.client.com"
```

When the allowlist is `'self'` the backend also sends `X-Frame-Options: SAMEORIGIN`; for a
multi-origin allowlist the CSP header is authoritative (there is no multi-origin
`X-Frame-Options`).

`AI_QUALITY_FRAME_ANCESTORS` resolves in **three** states, because unset is not one of its
valid values:

| State | Result |
| --- | --- |
| unset | the shipped default `'self'` |
| set, naming no origin (`""` or whitespace) | the service REFUSES to start |
| set to one or more origins | exactly those origins |

Reading the middle state as unset would emit the header
`Content-Security-Policy: frame-ancestors ` with an empty directive; browsers discard an
empty directive as a parse error, and the `'self'` branch that adds `X-Frame-Options` would
be skipped too, so the clickjacking restriction would disappear from both channels at once
with nothing in the response to say so. A config template that renders the variable empty
fails at boot instead. To forbid all framing, say so explicitly:

```bash
export AI_QUALITY_FRAME_ANCESTORS="'none'"
```

## 7. CORS (only for the cross-origin / standalone dev case)

Same-origin embedding needs no CORS. For a standalone dev UI on a different origin, set an
explicit per-tenant allowlist (never `*`):

```bash
export AI_QUALITY_CORS_ORIGINS="https://a4.client.com,https://staging.client.com"
```

The allowed methods are `GET`, `POST`, `OPTIONS`; the allowed headers are `Content-Type`,
`Authorization`, and `X-Dev-Persona`. With the variable unset the default is the local dev
origins (`http://localhost:3000`, `http://127.0.0.1:3000`).

## 8. Configuration reference

| Variable                     | Where     | Default             | Purpose                                              |
| ---------------------------- | --------- | ------------------- | ---------------------------------------------------- |
| `AI_QUALITY_PROFILE`         | backend   | `local`             | `local` \| `gcp` \| `platform` \| `onprem`           |
| `AI_QUALITY_IAP_AUDIENCE`    | backend   | (empty)             | Expected IAP audience; required in secure mode       |
| `AI_QUALITY_CORS_ORIGINS`    | backend   | dev origins         | Per-tenant CORS allowlist (comma-separated, never *) |
| `AI_QUALITY_FRAME_ANCESTORS` | backend   | `'self'` when unset | CSP frame-ancestors allowlist (space-separated); set-and-empty refuses to boot |
| `NEXT_PUBLIC_API_BASE`       | UI build  | `localhost:8084`    | Backend base URL (or same-origin `/agent/api`)       |
| `NEXT_PUBLIC_BASE_PATH`      | UI build  | (empty)             | Mount the UI under a reverse-proxy sub-path          |
| `NEXT_PUBLIC_EMBED`          | UI build  | (unset)             | `1` drops the app header/footer chrome               |
| `X-Dev-Persona`              | request   | first persona       | Local-only persona selector header                   |

## 9. Client-side integration checklist

- [ ] Decide the shape: same-origin reverse proxy (A), standalone behind IAP (B), or local (C).
- [ ] For A: reverse-proxy `/agent/*` (UI) and `/agent/api/*` (backend) under your origin.
- [ ] Build the UI with `NEXT_PUBLIC_BASE_PATH`, `NEXT_PUBLIC_EMBED=1`, and a same-origin
      `NEXT_PUBLIC_API_BASE`.
- [ ] Add your parent origin(s) to `AI_QUALITY_FRAME_ANCESTORS`.
- [ ] For B: configure Cloud IAP and set `AI_QUALITY_PROFILE=gcp` and `AI_QUALITY_IAP_AUDIENCE`.
- [ ] Confirm the request body carries no `actor`; the persona header (local) or IAP assertion
      (secure) supplies identity.
- [ ] Verify a run's audit event records the expected user as the actor.

## 10. Security checklist

- [ ] The request-body `actor` is ignored: identity is the server-verified `Principal`.
- [ ] Unknown persona (local) or missing / invalid assertion (secure) returns 401, not a
      default identity.
- [ ] `AI_QUALITY_CORS_ORIGINS` is an explicit allowlist, never `*`.
- [ ] `AI_QUALITY_FRAME_ANCESTORS` lists only the intended parent origins.
- [ ] The IAP assertion is never logged; audience is pinned via `AI_QUALITY_IAP_AUDIENCE`.
- [ ] GCP SDK imports stay lazy so the `local` / `onprem` profiles run SDK-free.

## 11. Further layers (out of scope here)

These are additional hardening layers, documented in the reference build
`cdd-sow-research` (`docs/embedding-and-identity.md`) rather than implemented here:

- Cross-origin embedding: a versioned SRI-pinned loader, a host / iframe postMessage
  contract, and a bearer-token-in-memory handoff instead of third-party cookies.
- "Launch in new tab" (Mode 6): a self-issued session cookie minted after an OIDC
  Authorization Code plus PKCE login, for hosts where framing or cross-site cookies are
  blocked.
- Per-hop OAuth2 token exchange (OBO) plus Workload Identity plus mTLS to the sibling Hrz
  services, and step-up (acr/amr) for high-value actions.
- Per-tenant, request-time framing / CORS / issuer policy and fail-closed ACL retrieval.
