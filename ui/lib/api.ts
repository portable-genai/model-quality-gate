/**
 * Typed fetch client for the A4 AI Quality & Model-Risk FastAPI backend.
 *
 * Routes (SPEC §6):
 *   POST /v1/evaluations  -> EvalReport
 *   POST /v1/redteam      -> RedTeamReport
 *   POST /v1/gate         -> GateDecision
 *   GET  /v1/gate         -> { passed }
 *   GET  /v1/personas     -> Persona[]   (local profile only)
 *   GET  /healthz         -> { status, profile, region }
 *
 * Identity: the backend resolves the audit actor server-side (never a body field). In
 * LOCAL mode it reads the X-Dev-Persona header (the persona picker's selection); in secure
 * profiles identity comes from an IAP assertion the platform injects, so the header is
 * ignored. See ../docs/embedding-and-identity.md.
 */

import type {
  EvalReport,
  GateDecision,
  HealthStatus,
  Persona,
  RedTeamReport,
} from "./types";
import { apiBase } from "./api-base.mjs";

// The literal member expression is required. A bundler substitutes a public variable only
// where it sees exactly `process.env.NEXT_PUBLIC_X`; handing this helper the whole
// `process.env` object leaves nothing to substitute, so the browser read undefined, took the
// loopback default below, and called a port its own page is not allowed to reach. The page
// rendered in full and reported its backend unreachable.
export const API_BASE = apiBase({ NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE });

// Dev-only identity selection. In LOCAL mode the backend resolves identity from the
// X-Dev-Persona header; in secure profiles this is ignored (identity comes from the
// IAP-verified assertion the platform injects).
let devPersona = "";

export function setDevPersona(id: string): void {
  devPersona = id;
}

export function getDevPersona(): string {
  return devPersona;
}

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(message: string, status: number, body: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export interface TargetInput {
  model: string;
  prompt_version: string;
  dataset_id: string;
  system?: string;
}

function jsonHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (devPersona) headers["X-Dev-Persona"] = devPersona;
  return headers;
}

async function parseJsonOrThrow(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail =
        (parsed && (parsed.detail || parsed.message || parsed.error)) || text;
    } catch {
      /* keep raw text */
    }
    throw new ApiError(
      `${res.status} ${res.statusText}: ${detail || "request failed"}`,
      res.status,
      text,
    );
  }
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError("Malformed JSON in response", res.status, text);
  }
}

function withTimeout(signal?: AbortSignal, ms = 60_000): AbortSignal {
  if (signal) return signal;
  const ctor = AbortSignal as typeof AbortSignal & {
    timeout?: (ms: number) => AbortSignal;
  };
  if (typeof ctor.timeout === "function") {
    return ctor.timeout(ms);
  }
  return new AbortController().signal;
}

// --------------------------------------------------------------------------- //
// Endpoints
// --------------------------------------------------------------------------- //
export async function evaluate(
  target: TargetInput,
  signal?: AbortSignal,
): Promise<EvalReport> {
  const res = await fetch(`${API_BASE}/v1/evaluations`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ target, dataset_id: target.dataset_id }),
    signal: withTimeout(signal),
  });
  return (await parseJsonOrThrow(res)) as EvalReport;
}

export async function redteam(
  target: TargetInput,
  signal?: AbortSignal,
): Promise<RedTeamReport> {
  const res = await fetch(`${API_BASE}/v1/redteam`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ target }),
    signal: withTimeout(signal),
  });
  return (await parseJsonOrThrow(res)) as RedTeamReport;
}

export async function gate(
  target: TargetInput,
  signal?: AbortSignal,
): Promise<GateDecision> {
  const res = await fetch(`${API_BASE}/v1/gate`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ target, dataset_id: target.dataset_id }),
    signal: withTimeout(signal),
  });
  return (await parseJsonOrThrow(res)) as GateDecision;
}

export async function listPersonas(signal?: AbortSignal): Promise<Persona[]> {
  try {
    const res = await fetch(`${API_BASE}/v1/personas`, {
      method: "GET",
      headers: jsonHeaders(),
      signal: withTimeout(signal, 8_000),
    });
    if (!res.ok) return [];
    return (await res.json()) as Persona[];
  } catch {
    return [];
  }
}

export async function healthz(signal?: AbortSignal): Promise<HealthStatus> {
  try {
    const res = await fetch(`${API_BASE}/healthz`, {
      method: "GET",
      signal: withTimeout(signal, 8_000),
    });
    // The down fallbacks carry EMPTY provenance, not "?" like the other fields. "?" is a
    // legible placeholder for a profile the console could not read; an empty runtime is what
    // the banner keys off to render nothing at all, and stating "running ?" would be an
    // assertion about provenance the service never made.
    if (!res.ok)
      return { status: "down", profile: "?", runtime: "", generator_model: "", region: "?" };
    return (await res.json()) as HealthStatus;
  } catch {
    return { status: "down", profile: "?", runtime: "", generator_model: "", region: "?" };
  }
}

export const api = { evaluate, redteam, gate, listPersonas, healthz };
