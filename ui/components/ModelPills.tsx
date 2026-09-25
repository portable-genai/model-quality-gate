"use client";

import { useEffect, useState } from "react";

import { watchAnswers } from "../lib/answer-provenance.mjs";
import { API_BASE, healthz } from "../lib/api";

/**
 * Two small pills at the top right of every page: the model that ANSWERED, and `Search` when
 * the answer used an online search tool (owner decision, 2026-09-23; they replace the
 * full-width provenance banner).
 *
 * The pill names what answered, not what configuration would call. Until an answer arrives it
 * shows the service's configured `generator_model` from `/healthz`, dimmed, with where the
 * runtime sits in its title. From then on it shows the `X-Answered-By` header of the console's
 * last answering response, solid, and `Search` appears only while that response carried
 * `X-Search-Used: true`. Both headers are emitted by the service (`install_answer_provenance`
 * in `api/app.py`, which also names them in `Access-Control-Expose-Headers` so a cross-origin
 * console can read them).
 *
 * This matters more here than anywhere: the gate is demonstrated on a laptop and on the
 * deployment, sometimes in the same hour, and a verdict read off a deterministic offline stub
 * must never be mistaken for one a managed model produced.
 *
 * **Every value comes from the service**, and nothing here infers one. Health and the fetch
 * wrapper use the same `API_BASE` as every other call this console makes, resolved once in
 * `lib/api`; the `connect-src` this console ships is built from that same value, so a base of
 * their own would be silently refused and the pills would render nothing.
 */

interface Configured {
  model: string;
  where: string;
}

interface Answer {
  model: string;
  search: boolean;
}

/**
 * Renders once the service has answered `/healthz`, and nothing before that.
 *
 * The null-until-known state is deliberate: a pill defaulting to a model or a runtime while the
 * fetch is in flight would state a falsehood on some page load, and a failed health call (which
 * `healthz` reports with an EMPTY runtime) renders nothing for the same reason. The page's own
 * error surface owns the failure.
 */
export function ModelPills() {
  const [configured, setConfigured] = useState<Configured | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);

  useEffect(() => {
    let live = true;
    const stop = watchAnswers(window, API_BASE, (next) => {
      if (live) setAnswer(next);
    });
    healthz()
      .then((status) => {
        if (!live || !status.runtime) return;
        setConfigured({
          model: status.generator_model,
          where: status.runtime === "gcp" ? "running on GCP" : "running locally",
        });
      })
      .catch(() => undefined);
    return () => {
      live = false;
      stop();
    };
  }, []);

  if (!configured) return null;
  return (
    <div className="model-pills" data-testid="model-pills">
      {answer ? (
        <span className="model-pill answered" data-state="answered" title="answered the last request">
          {answer.model}
        </span>
      ) : (
        <span className="model-pill configured" data-state="configured" title={configured.where}>
          {configured.model}
        </span>
      )}
      {answer?.search ? (
        <span className="model-pill search" title="the last answer used an online search tool">
          Search
        </span>
      ) : null}
    </div>
  );
}
