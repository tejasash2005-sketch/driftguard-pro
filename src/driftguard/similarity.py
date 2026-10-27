"""Text similarity: lexical by default, embeddings optional.

All functions return a float in ``[0, 1]``. Identical inputs return exactly ``1.0``.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from collections.abc import Callable, Sequence
from difflib import SequenceMatcher
from functools import lru_cache, partial

from .errors import EmbeddingUnavailableError, InvalidInputError

Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]
SimilarityFn = Callable[[str, str], float]

MAX_INPUT_CHARS = 1_000_000
# SequenceMatcher is super-linear; beyond this many tokens a linear bigram measure is used.
MAX_SEQUENCE_TOKENS = 2000
# Words, or single punctuation/symbol characters, so "Hello!" differs from "Hello".
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def _check(a: object, b: object) -> None:
    for label, value in (("first", a), ("second", b)):
        if not isinstance(value, str):
            raise InvalidInputError(f"{label} argument must be str, got {type(value).__name__}")
        if len(value) > MAX_INPUT_CHARS:
            raise InvalidInputError(f"{label} argument exceeds {MAX_INPUT_CHARS} characters")


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, round(value, 12)))


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _bigram_jaccard(a: list[str], b: list[str]) -> float:
    ca, cb = Counter(zip(a, a[1:], strict=False)), Counter(zip(b, b[1:], strict=False))
    union = sum((ca | cb).values())
    return sum((ca & cb).values()) / union if union else 1.0


def lexical_similarity(a: str, b: str) -> float:
    """Blend of multiset token Jaccard and token-sequence ratio.

    Case and whitespace are ignored. Two empty strings are identical (1.0); an empty
    and a non-empty string have similarity 0.0. Non-``str`` inputs raise
    :class:`InvalidInputError`.
    """
    _check(a, b)
    if a == b:
        return 1.0
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return 1.0
    if not na or not nb:
        return 0.0
    tokens_a, tokens_b = _TOKEN_RE.findall(na), _TOKEN_RE.findall(nb)
    count_a, count_b = Counter(tokens_a), Counter(tokens_b)
    intersection = sum((count_a & count_b).values())
    union = sum((count_a | count_b).values())
    jaccard = intersection / union
    if max(len(tokens_a), len(tokens_b)) > MAX_SEQUENCE_TOKENS:
        sequence = _bigram_jaccard(tokens_a, tokens_b)
    else:
        sequence = SequenceMatcher(None, tokens_a, tokens_b, autojunk=False).ratio()
    return _clamp(0.5 * jaccard + 0.5 * sequence)


@lru_cache(maxsize=1)
def default_embedder() -> Embedder:
    """Load the optional sentence-transformers model (``driftguard-pro[embeddings]``)."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingUnavailableError(
            "embedding similarity requires the optional extra: "
            'python -m pip install "driftguard-pro[embeddings]"'
        ) from exc
    model = SentenceTransformer(os.environ.get("DRIFTGUARD_EMBEDDING_MODEL", "all-MiniLM-L6-v2"))

    def embed(texts: Sequence[str]) -> list[list[float]]:
        return [[float(x) for x in row] for row in model.encode(list(texts))]

    return embed


def embedding_similarity(a: str, b: str, embedder: Embedder | None = None) -> float:
    """Cosine similarity of embeddings, clamped to ``[0, 1]``."""
    _check(a, b)
    if a == b:
        return 1.0
    blank_a, blank_b = not a.strip(), not b.strip()
    if blank_a and blank_b:
        return 1.0
    if blank_a or blank_b:
        return 0.0
    vectors = (embedder or default_embedder())([a, b])
    if len(vectors) != 2 or len(vectors[0]) != len(vectors[1]) or not len(vectors[0]):
        raise InvalidInputError("embedder must return two non-empty vectors of equal length")
    va, vb = vectors
    if not all(math.isfinite(x) for x in (*va, *vb)):
        raise InvalidInputError("embedder returned non-finite values")
    norm_a = math.sqrt(math.fsum(x * x for x in va))
    norm_b = math.sqrt(math.fsum(x * x for x in vb))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    cosine = math.fsum(x * y for x, y in zip(va, vb, strict=True)) / (norm_a * norm_b)
    return _clamp(cosine)


def get_similarity_fn(method: str, embedder: Embedder | None = None) -> SimilarityFn:
    if method == "lexical":
        return lexical_similarity
    if method == "embedding":
        resolved = embedder or default_embedder()  # fail early if unavailable
        return partial(embedding_similarity, embedder=resolved)
    raise InvalidInputError(f"unknown similarity method: {method!r}")
