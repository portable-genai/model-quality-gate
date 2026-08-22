"use client";

import type { EvalReport } from "@/lib/types";
import { ScoreBar, SectionLabel, VerdictBadge } from "./ui";

/** Renders an EvalReport: per-metric score vs threshold, with the overall verdict. */
export function EvalReportView({ report }: { report: EvalReport }) {
  return (
    <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
      <div className="mb-3 flex items-center justify-between">
        <SectionLabel>Evaluation report</SectionLabel>
        <VerdictBadge passed={report.passed} />
      </div>
      <p className="mb-3 text-xs text-ink-500">
        {report.target.model} @ {report.target.prompt_version} ·{" "}
        {report.n_examples} golden examples
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-ink-400">
            <th className="pb-1.5">Metric</th>
            <th className="pb-1.5">Score</th>
            <th className="pb-1.5">Threshold</th>
            <th className="pb-1.5 text-right">Result</th>
          </tr>
        </thead>
        <tbody>
          {report.results.map((r) => (
            <tr key={r.metric} className="border-t border-ink-100">
              <td className="py-2 font-medium text-ink-800">{r.metric}</td>
              <td className="py-2">
                <div className="flex items-center gap-2">
                  <ScoreBar
                    score={r.score}
                    threshold={r.threshold}
                    passed={r.passed}
                  />
                  <span className="tabular-nums text-ink-700">
                    {r.score.toFixed(3)}
                  </span>
                </div>
              </td>
              <td className="py-2 tabular-nums text-ink-500">
                {r.threshold.toFixed(2)}
              </td>
              <td className="py-2 text-right">
                <span
                  className={
                    r.passed
                      ? "text-xs font-semibold text-emerald-600"
                      : "text-xs font-semibold text-rose-600"
                  }
                >
                  {r.passed ? "pass" : "fail"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
