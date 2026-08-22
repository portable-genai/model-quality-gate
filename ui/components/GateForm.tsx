"use client";

import { useState } from "react";
import { api, ApiError, type TargetInput } from "@/lib/api";
import type { EvalReport, GateDecision, RedTeamReport } from "@/lib/types";

type Action = "gate" | "evaluate" | "redteam";

export interface RunResult {
  action: Action;
  gate?: GateDecision;
  evalReport?: EvalReport;
  redteam?: RedTeamReport;
}

/** The target-input form: choose a model + prompt version + dataset, then run an action. */
export function GateForm({
  onResult,
  onError,
}: {
  onResult: (result: RunResult) => void;
  onError: (message: string | null) => void;
}) {
  const [model, setModel] = useState("gemini-3.5-flash");
  const [promptVersion, setPromptVersion] = useState("v3");
  const [datasetId, setDatasetId] = useState("compliance-qa-golden");
  const [busy, setBusy] = useState<Action | null>(null);

  async function run(action: Action) {
    const target: TargetInput = {
      model,
      prompt_version: promptVersion,
      dataset_id: datasetId,
    };
    setBusy(action);
    onError(null);
    try {
      if (action === "gate") {
        onResult({ action, gate: await api.gate(target) });
      } else if (action === "evaluate") {
        onResult({ action, evalReport: await api.evaluate(target) });
      } else {
        onResult({ action, redteam: await api.redteam(target) });
      }
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : `Request failed: ${String(e)}`;
      onError(msg);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Model" value={model} onChange={setModel} />
        <Field
          label="Prompt version"
          value={promptVersion}
          onChange={setPromptVersion}
        />
        <Field
          label="Dataset id"
          value={datasetId}
          onChange={setDatasetId}
        />
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => run("gate")}
          disabled={busy !== null}
          className="rounded-lg bg-regblue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-regblue-700 disabled:opacity-50"
        >
          {busy === "gate" ? "Running gate..." : "Run promotion gate"}
        </button>
        <button
          type="button"
          onClick={() => run("evaluate")}
          disabled={busy !== null}
          className="rounded-lg border border-ink-300 px-4 py-2 text-sm font-semibold text-ink-700 hover:bg-ink-50 disabled:opacity-50"
        >
          Evaluate only
        </button>
        <button
          type="button"
          onClick={() => run("redteam")}
          disabled={busy !== null}
          className="rounded-lg border border-ink-300 px-4 py-2 text-sm font-semibold text-ink-700 hover:bg-ink-50 disabled:opacity-50"
        >
          Red-team only
        </button>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-500">
        {label}
      </span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm text-ink-800 focus:border-regblue-400 focus:outline-none focus:ring-2 focus:ring-regblue-100"
      />
    </label>
  );
}
