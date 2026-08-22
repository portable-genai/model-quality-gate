/** One build-time API-base contract shared by the client and the CSP. */
const DEFAULT_API_BASE = "http://localhost:8084";

export function apiBase(env) {
  const configured = env.NEXT_PUBLIC_API_BASE;
  const raw = configured === undefined ? DEFAULT_API_BASE : configured.trim();
  if (!raw) return "";
  if (raw.startsWith("/") && !raw.startsWith("//")) return raw.replace(/\/+$/, "");
  const parsed = new URL(raw);
  const loopback = parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1";
  if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && loopback)) {
    throw new Error("NEXT_PUBLIC_API_BASE must be HTTPS outside loopback");
  }
  return raw.replace(/\/+$/, "");
}

export function apiOrigin(env) {
  const base = apiBase(env);
  return base.startsWith("/") || !base ? "" : new URL(base).origin;
}
