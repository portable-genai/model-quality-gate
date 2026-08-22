import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "A4 AI Quality & Model-Risk Platform",
  description:
    "The production-promotion eval / red-team gate and model-risk (MRM) evidence system for APAC banking.",
};

// Required by the nonce-based CSP in `lib/csp.mjs`, not a performance preference. Next can
// only stamp a per-request nonce onto the scripts of a DYNAMICALLY rendered route; a
// statically prerendered page was built before the nonce existed, so the browser blocks every
// script and the console renders as dead HTML. `assertHydratableCsp` fails the build if this
// line is removed. The console resolves identity per request anyway, so nothing here could
// have been safely cached across tenants by a static render.
export const dynamic = "force-dynamic";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // EMBED mode: the host page owns the chrome, so drop the full-height background wrapper
  // and let the host's layout surround the mounted UI. The page-level header/footer are
  // hidden too (see app/page.tsx). Set NEXT_PUBLIC_EMBED=1 at build time to enable.
  const embed = process.env.NEXT_PUBLIC_EMBED === "1";
  return (
    <html lang="en">
      <body className={embed ? undefined : "min-h-screen"}>{children}</body>
    </html>
  );
}
