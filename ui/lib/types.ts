/**
 * TypeScript mirrors of the A4 domain dataclasses.
 *
 * Source of truth: `src/model_quality_gate/domain/models.py`.
 * The backend serialises dataclasses with `domain/serialization.to_jsonable`
 * (SPEC §5): dataclass field names are preserved (snake_case) and every enum is
 * rendered as its `.value` string. These types follow that contract exactly.
 */

// --------------------------------------------------------------------------- //
// Target & dataset
// --------------------------------------------------------------------------- //
export interface EvalTarget {
  model: string;
  prompt_version: string;
  dataset_id: string;
  system: string;
}

// --------------------------------------------------------------------------- //
// Evaluation
// --------------------------------------------------------------------------- //
export type EvalMetric =
  | "groundedness"
  | "citation_accuracy"
  | "faithfulness"
  | "safety";

export interface EvalMetricResult {
  metric: string;
  score: number;
  threshold: number;
  passed: boolean;
}

export interface EvalReport {
  target: EvalTarget;
  results: EvalMetricResult[];
  n_examples: number;
  passed: boolean;
}

// --------------------------------------------------------------------------- //
// Red-team
// --------------------------------------------------------------------------- //
export type RedTeamCategory =
  | "prompt_injection"
  | "jailbreak"
  | "pii_exfil"
  | "harmful_content"
  | "hallucination";

export interface RedTeamResult {
  category: RedTeamCategory;
  probe_id: string;
  blocked: boolean;
  passed: boolean;
  detail: string;
}

export interface RedTeamReport {
  target: EvalTarget;
  results: RedTeamResult[];
  passed: boolean;
}

// --------------------------------------------------------------------------- //
// Gate decision
// --------------------------------------------------------------------------- //
export interface GateDecision {
  target: EvalTarget;
  eval_report: EvalReport;
  redteam_report: RedTeamReport;
  passed: boolean;
  model_card_ref: string;
  mrm_evidence_ref: string;
  requires_human_review: boolean;
  caveats: string[];
}

// --------------------------------------------------------------------------- //
// MRM evidence
// --------------------------------------------------------------------------- //
export interface PromptVersion {
  name: string;
  version: string;
  template: string;
  checksum: string;
  created_at: string;
}

export interface ModelCard {
  model: string;
  version: string;
  intended_use: string;
  metrics: Record<string, number>;
  limitations: string[];
  owner: string;
  created_at: string;
}

export interface HealthStatus {
  status: string;
  profile: string;
  region: string;
}

// A seeded dev persona (local profile only), listed by GET /v1/personas and selected in
// the "Demo identity" picker. The chosen id is sent as the X-Dev-Persona header so the
// backend resolves the audit actor from a verified Principal, never a client-supplied value.
export interface Persona {
  id: string;
  subject: string;
  tenant: string;
  principals: string;
}

export const REDTEAM_LABEL: Record<RedTeamCategory, string> = {
  prompt_injection: "Prompt injection",
  jailbreak: "Jailbreak",
  pii_exfil: "PII exfiltration",
  harmful_content: "Harmful content",
  hallucination: "Hallucination",
};
