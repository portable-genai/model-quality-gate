"use client";

/**
 * Shared presentational primitives for the A4 console.
 */

/**
 * Prominent maker-checker banner (General Principle P-06). Rendered whenever a
 * GateDecision carries `requires_human_review`: a borderline PASS is gated for a
 * model-risk officer to sign off before the target is promoted.
 */
export function HumanReviewBanner({
  reason,
  compact = false,
}: {
  reason?: string;
  compact?: boolean;
}) {
  return (
    <div
      role="status"
      className={`flex items-start gap-3 rounded-lg border-l-4 border-amber-500 bg-amber-50 ${
        compact ? "p-2.5" : "p-3.5"
      } text-amber-900 ring-1 ring-inset ring-amber-200`}
    >
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="mt-0.5 h-5 w-5 shrink-0 text-amber-600"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <path
          d="M12 9v4m0 4h.01M10.3 3.86 1.82 18a2 2 0 0 0 1.7 3h16.96a2 2 0 0 0 1.7-3L13.7 3.86a2 2 0 0 0-3.42 0Z"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Human review required</span>
          <span className="rounded-full bg-amber-200/70 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-800">
            Maker / Checker
          </span>
        </div>
        <p className="mt-0.5 text-xs leading-relaxed text-amber-800">
          {reason ??
            "This promotion is borderline and is gated for sign-off by a model-risk officer before the target can be promoted."}
        </p>
      </div>
    </div>
  );
}

export function VerdictBadge({ passed }: { passed: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-bold uppercase tracking-wide ring-1 ring-inset ${
        passed
          ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
          : "bg-rose-50 text-rose-700 ring-rose-200"
      }`}
    >
      {passed ? "PASS" : "FAIL"}
    </span>
  );
}

export function ScoreBar({
  score,
  threshold,
  passed,
}: {
  score: number;
  threshold: number;
  passed: boolean;
}) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  const thresholdPct = Math.max(0, Math.min(1, threshold)) * 100;
  const tone = passed ? "bg-emerald-500" : "bg-rose-500";
  return (
    <div className="relative h-2 w-40 overflow-hidden rounded-full bg-ink-200">
      <div className={`h-full rounded-full ${tone}`} style={{ width: `${pct}%` }} />
      <div
        className="absolute top-0 h-full w-0.5 bg-ink-700"
        style={{ left: `${thresholdPct}%` }}
        title={`threshold ${threshold.toFixed(2)}`}
      />
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-ink-200 bg-white/60 px-6 py-12 text-center">
      <p className="text-sm font-medium text-ink-700">{title}</p>
      {hint && <p className="mt-1 max-w-xs text-xs text-ink-400">{hint}</p>}
    </div>
  );
}

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">
      {children}
    </div>
  );
}
