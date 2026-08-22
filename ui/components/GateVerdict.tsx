"use client";

import type { GateDecision } from "@/lib/types";
import { EvalReportView } from "./EvalReportView";
import { RedTeamView } from "./RedTeamView";
import { HumanReviewBanner, SectionLabel, VerdictBadge } from "./ui";

/**
 * Renders a full GateDecision: the overall verdict, the MRM evidence pointers, the
 * maker-checker banner for a borderline pass, and the two underlying reports.
 */
export function GateVerdict({ decision }: { decision: GateDecision }) {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
        <div className="flex items-center justify-between">
          <div>
            <SectionLabel>Promotion gate verdict</SectionLabel>
            <p className="mt-1 text-sm font-semibold text-ink-800">
              {decision.target.model} @ {decision.target.prompt_version}
            </p>
          </div>
          <VerdictBadge passed={decision.passed} />
        </div>

        <dl className="mt-3 grid grid-cols-1 gap-1 text-xs text-ink-600 sm:grid-cols-2">
          <div>
            <dt className="font-semibold text-ink-500">Model card</dt>
            <dd className="font-mono">{decision.model_card_ref || "n/a"}</dd>
          </div>
          <div>
            <dt className="font-semibold text-ink-500">MRM evidence</dt>
            <dd className="font-mono">{decision.mrm_evidence_ref || "n/a"}</dd>
          </div>
        </dl>

        {decision.caveats.length > 0 && (
          <ul className="mt-3 list-disc space-y-0.5 pl-5 text-xs text-ink-500">
            {decision.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        )}
      </div>

      {decision.requires_human_review && <HumanReviewBanner />}

      <EvalReportView report={decision.eval_report} />
      <RedTeamView report={decision.redteam_report} />
    </div>
  );
}
