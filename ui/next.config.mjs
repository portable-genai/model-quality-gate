/** @type {import('next').NextConfig} */
// The Content-Security-Policy and X-Frame-Options are NOT set here. They carry a per-request
// script nonce, which a static `headers()` table cannot express, so `proxy.ts` owns them and
// builds them from `lib/csp.mjs`. Setting the policy in both places would hand the browser two
// policies to intersect, and the stricter one wins, which would reinstate the bare `script-src
// 'self'` that stopped this console hydrating in the first place.
//
// What IS here is the refusal: `next build` and `next start` both evaluate this file at module
// scope, so a layout that has lost its `force-dynamic` (and therefore cannot carry the nonce)
// fails the build instead of shipping a console whose controls silently do nothing.
import { readFileSync } from "node:fs";

import { assertHydratableCsp } from "./lib/csp.mjs";

assertHydratableCsp(readFileSync(new URL("./app/layout.tsx", import.meta.url), "utf8"));
// Mount the UI under a reverse-proxy sub-path (e.g. /agent) for same-origin embedding by
// setting NEXT_PUBLIC_BASE_PATH at build time. Blank keeps the standalone deployment
// unchanged. See ../docs/embedding-and-identity.md.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  reactStrictMode: true,
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          // The console is served over TLS everywhere except a laptop dev server, and
          // browsers ignore HSTS on an http://localhost response.
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
