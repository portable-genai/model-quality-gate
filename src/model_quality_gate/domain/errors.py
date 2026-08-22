"""Domain exceptions for the AI Quality & Model-Risk Platform (system A4).

Pure-Python exception hierarchy raised by the orchestration services. The domain
layer never imports Google Cloud, ADK, or any framework : these errors let callers
(API, CLI, the Agent Runtime adapter) react to domain-level failures without
coupling to any vendor SDK error type.
"""

from __future__ import annotations


class AiQualityError(Exception):
    """Base class for all domain-level errors raised by A4 services."""


class EmptyDatasetError(AiQualityError):
    """Raised when an evaluation is requested over a dataset with no examples.

    An evaluation gate must never wave a target through on an empty golden set: a
    vacuous PASS is worse than a hard error, because it looks like a real result.
    """


class UnknownMetricError(AiQualityError):
    """Raised when an eval/gate request names a metric or bundle the registry does not know.

    Fail-closed: an unrecognised metric name must be a hard error, never silently scored
    against a 0.0 threshold (which any score clears, a false PASS). The API maps this to a
    422 so a caller sending a typo or an unregistered vertical metric is told, not waved
    through.
    """


class RedTeamError(AiQualityError):
    """Raised when the red-team harness cannot run the requested probes."""


class AssurancePersistenceError(AiQualityError):
    """Raised when required promotion evidence or immutable audit cannot be persisted.

    A promotion verdict without durable evidence is not an approvable verdict.  The API
    therefore fails closed instead of returning a PASS carrying logical-only references.
    """
