"use client";

import { REDTEAM_LABEL, type RedTeamReport } from "@/lib/types";
import { SectionLabel, VerdictBadge } from "./ui";

/** Renders a RedTeamReport: per-probe blocked/passed across the five attack families. */
export function RedTeamView({ report }: { report: RedTeamReport }) {
  return (
    <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
      <div className="mb-3 flex items-center justify-between">
        <SectionLabel>Red-team report</SectionLabel>
        <VerdictBadge passed={report.passed} />
      </div>
      <ul className="space-y-2">
        {report.results.map((r) => (
          <li
            key={r.probe_id}
            className="flex items-start justify-between gap-3 rounded-lg border border-ink-100 p-2.5"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-ink-800">
                  {REDTEAM_LABEL[r.category] ?? r.category}
                </span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                    r.blocked
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-rose-50 text-rose-700"
                  }`}
                >
                  {r.blocked ? "blocked" : "not blocked"}
                </span>
              </div>
              {r.detail && (
                <p className="mt-0.5 truncate text-xs text-ink-400">{r.detail}</p>
              )}
            </div>
            <span
              className={
                r.passed
                  ? "text-xs font-semibold text-emerald-600"
                  : "text-xs font-semibold text-rose-600"
              }
            >
              {r.passed ? "safe" : "unsafe"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
