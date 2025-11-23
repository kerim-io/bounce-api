"""Exceptions for generative AI operations."""


class GenerationError(Exception):
    """Raised when generative model creation fails after all retries."""
