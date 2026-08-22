"use client";

import { useEffect, useState } from "react";
import { api, setDevPersona } from "@/lib/api";
import type { HealthStatus, Persona } from "@/lib/types";
import { EvalReportView } from "@/components/EvalReportView";
import { GateForm, type RunResult } from "@/components/GateForm";
import { GateVerdict } from "@/components/GateVerdict";
import { RedTeamView } from "@/components/RedTeamView";
import { EmptyState } from "@/components/ui";

const IS_EMBEDDED = process.env.NEXT_PUBLIC_EMBED === "1";

export default function Home() {
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const status = await api.healthz();
      if (cancelled) return;
      setHealth(status);
      // The persona picker is a LOCAL-only demo convenience: secure profiles resolve
      // identity from the IAP assertion, so GET /v1/personas returns an empty list there.
      if (status.profile !== "local") return;
      const list = await api.listPersonas();
      if (cancelled || list.length === 0) return;
      setPersonas(list);
      setSelectedPersona(list[0].id);
      setDevPersona(list[0].id);
    })().catch(() => {
      if (!cancelled) setHealth(null);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  function onPersonaChange(id: string) {
    setSelectedPersona(id);
    setDevPersona(id);
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      {!IS_EMBEDDED && (
        <header className="mb-6">
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-bold text-ink-900">
              A4 AI Quality &amp; Model-Risk Platform
            </h1>
            {health && (
              <span
                className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                  health.status === "ok"
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-rose-50 text-rose-700"
                }`}
              >
                {health.status === "ok"
                  ? `${health.profile} · ${health.region}`
                  : "backend offline"}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-ink-500">
            Run the promotion gate, the evaluation, or the red-team harness for a
            target (model + prompt version + golden dataset). A target passes only
            if every eval metric clears its threshold and every probe is blocked.
          </p>
        </header>
      )}

      {personas.length > 0 && (
        <section className="mb-4 rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
          <label className="block text-sm">
            <span className="font-medium text-ink-700">Demo identity</span>
            <span className="mt-0.5 block text-xs text-ink-500">
              Local mode only. The chosen persona is sent as the audit actor
              (X-Dev-Persona); it is ignored in secure mode.
            </span>
            <select
              className="mt-2 w-full rounded-lg border border-ink-200 px-2.5 py-1.5 text-sm sm:w-96"
              value={selectedPersona}
              onChange={(e) => onPersonaChange(e.target.value)}
            >
              {personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.subject} · {p.tenant}
                </option>
              ))}
            </select>
          </label>
        </section>
      )}

      <GateForm onResult={setResult} onError={setError} />

      {error && (
        <div className="mt-4 rounded-lg border-l-4 border-rose-500 bg-rose-50 p-3 text-sm text-rose-800">
          {error}
        </div>
      )}

      <section className="mt-6">
        {!result && !error && (
          <EmptyState
            title="No run yet"
            hint="Choose a target above and run the gate to see the EvalReport, RedTeamReport, and the PASS/FAIL verdict with MRM evidence."
          />
        )}
        {result?.action === "gate" && result.gate && (
          <GateVerdict decision={result.gate} />
        )}
        {result?.action === "evaluate" && result.evalReport && (
          <EvalReportView report={result.evalReport} />
        )}
        {result?.action === "redteam" && result.redteam && (
          <RedTeamView report={result.redteam} />
        )}
      </section>

      {!IS_EMBEDDED && (
        <footer className="mt-10 border-t border-ink-100 pt-4 text-xs text-ink-400">
          Reference build. Not affiliated with, endorsed by, or sponsored by Google
          LLC. Google Cloud product names are used descriptively only.
        </footer>
      )}
    </main>
  );
}
