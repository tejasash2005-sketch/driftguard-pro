"""Exception hierarchy. Every expected failure derives from DriftGuardError."""

from __future__ import annotations


class DriftGuardError(Exception):
    """Base class for all expected DriftGuard errors."""


class SuiteLoadError(DriftGuardError):
    """A suite, fixture, config or report file could not be read or validated."""


class NotFoundError(DriftGuardError):
    """A requested resource does not exist."""


class AssertionConfigError(DriftGuardError):
    """An assertion is misconfigured (for example an invalid JSON Schema)."""


class InvalidInputError(DriftGuardError, TypeError):
    """A function received an input of the wrong type or an unusable value."""


class StatsError(DriftGuardError, ValueError):
    """Statistical routines received invalid data."""


class ProviderError(DriftGuardError):
    """An LLM provider call failed."""


class MissingAPIKeyError(ProviderError):
    """The required API key environment variable is not set."""


class EmbeddingUnavailableError(DriftGuardError):
    """Embedding similarity was requested but no embedder is available."""
