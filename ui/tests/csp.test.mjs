import assert from "node:assert/strict";
import test from "node:test";

import { apiBase, apiOrigin } from "../lib/api-base.mjs";
import { WildcardOriginError, contentSecurityPolicy, frameAncestors } from "../lib/csp.mjs";

test("client and CSP share one API base", () => {
  const env = { NEXT_PUBLIC_API_BASE: "https://quality.bank.example/api/" };
  assert.equal(apiBase(env), "https://quality.bank.example/api");
  assert.equal(apiOrigin(env), "https://quality.bank.example");
  assert.match(contentSecurityPolicy(env, "nonce"), /connect-src 'self' https:\/\/quality\.bank\.example/);
});

test("a rooted reverse-proxy path stays same-origin", () => {
  const env = { NEXT_PUBLIC_API_BASE: "/apps/hrz4/api" };
  assert.equal(apiBase(env), "/apps/hrz4/api");
  assert.equal(apiOrigin(env), "");
});

test("plaintext non-loopback API origins are refused", () => {
  assert.throws(
    () => apiBase({ NEXT_PUBLIC_API_BASE: "http://quality.bank.example" }),
    /must be HTTPS outside loopback/,
  );
});

test("a wildcard frame-ancestors is refused in every spelling a config can render", () => {
  // The FastAPI half already refuses a bare asterisk. This is the OTHER emitter, and it is the
  // one a browser honours for the document, so closing only the service side left the console
  // framable by any origin while every check stayed green.
  for (const wildcard of ["*", "'*'", "null", "*.*"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: wildcard }),
      WildcardOriginError,
      `${JSON.stringify(wildcard)} must be refused, not passed through to the header`,
    );
  }
  assert.throws(
    () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.bank.example *" }),
    WildcardOriginError,
    "a wildcard standing beside named origins is still a wildcard",
  );
  assert.throws(
    () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "*,https://portal.bank.example" }),
    WildcardOriginError,
    "a comma is not CSP list syntax, so a comma-joined wildcard must still be seen",
  );
  // A HOST-SOURCE wildcard is the spelling an exact-token set misses, and CSP honours it: every
  // subdomain may frame the console, including one an attacker takes over or registers on a
  // user-content domain. A real origin never contains an asterisk, so refusing the character
  // outright turns away nothing a deployment could correctly hold.
  for (const hostSource of [
    "https://*.bank.example",
    "*.bank.example",
    "https://*",
    "https://portal.bank.example https://*.evil.example",
  ]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: hostSource }),
      WildcardOriginError,
      `${JSON.stringify(hostSource)} is a host-source wildcard and must be refused`,
    );
  }
});

test("the policy the proxy actually serves refuses a wildcard too", () => {
  // `contentSecurityPolicy` is what `proxy.ts` puts on the document response. Refusing inside
  // the resolver alone would be theatre if this path could still build a policy around it.
  for (const wildcard of ["*", "'*'", "null", "*.*", "https://*.bank.example"]) {
    assert.throws(
      () => contentSecurityPolicy({ NEXT_PUBLIC_FRAME_ANCESTORS: wildcard }, "n0nce"),
      WildcardOriginError,
      `the served document policy must not carry frame-ancestors ${wildcard}`,
    );
  }
});

test("a legitimate named allowlist is unaffected by the wildcard refusal", () => {
  // A refusal that also refuses valid input is an outage, not a control.
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.bank.example" }),
    "https://portal.bank.example",
  );
  assert.equal(
    frameAncestors({
      NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.bank.example https://intranet.bank.example",
    }),
    "https://portal.bank.example https://intranet.bank.example",
  );
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "'self'" }), "'self'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "'none'" }), "'none'");
  assert.match(
    contentSecurityPolicy({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.bank.example" }, "n"),
    /frame-ancestors https:\/\/portal\.bank\.example/,
  );
});

test("unset is the only state that takes the shipped default", () => {
  // Asserting that an EMPTIED value also resolves to 'self' would pin, deliberately,
  // as "the behaviour as found" while the wildcard change was kept narrow. That made it a test
  // holding a fail-open in place: whoever fixed the two-state read would have broken a green
  // test and been invited to revert the fix. The reconciliation it deferred has now happened,
  // so it is rewritten into the guard for the fix rather than deleted, which is the only way
  // the next reader learns that the old behaviour was a defect and not a preference.
  assert.equal(frameAncestors({}), "'self'");
  assert.match(contentSecurityPolicy({}, "n"), /frame-ancestors 'self'/);
});

test("a value that names no origin refuses, in either spelling", () => {
  // Two states that both name nothing, and both used to go wrong differently. An empty string
  // was falsy and silently took the 'self' default, so a deliberate blanking was read as
  // consent and a deployment that LOST the variable looked identical to one locked down on
  // purpose. A whitespace-only value is truthy in JavaScript and was emitted verbatim, giving
  // `frame-ancestors    `, an empty directive that browsers discard as a parse error, which
  // removes the framing restriction entirely. The service half already refused both.
  for (const blank of ["", "   ", "\t", "\n", " , , "]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: blank }),
      WildcardOriginError,
      `NEXT_PUBLIC_FRAME_ANCESTORS=${JSON.stringify(blank)} was accepted`,
    );
  }
});

test("unset keeps the restrictive default, and a named allowlist still resolves", () => {
  // The other half: a refusal that also refuses valid input, or that loses the unset default,
  // is an outage rather than a control.
  assert.equal(frameAncestors({}), "'self'");
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.bank.example" }),
    "https://portal.bank.example",
  );
  assert.equal(
    frameAncestors({
      NEXT_PUBLIC_FRAME_ANCESTORS: " https://portal.bank.example  https://ops.bank.example ",
    }),
    "https://portal.bank.example https://ops.bank.example",
  );
});
