from __future__ import annotations

import pytest

from driftguard.errors import EmbeddingUnavailableError, InvalidInputError
from driftguard.similarity import (
    default_embedder,
    embedding_similarity,
    get_similarity_fn,
    lexical_similarity,
)

IDENTICAL = [
    "hello",
    "Hello, world!",
    "The quick brown fox jumps over the lazy dog. " * 7,
    "unicode: caf\u00e9 \u65e5\u672c\u8a9e \U0001f600",
    "!!! ??? ...",
    "a b c d e f g h i j k l m n o p q r s t u v w x y z",
    '{"status": "shipped", "eta_days": 3, "carrier": "DHL"}',
    "x",
    " leading and trailing ",
]


@pytest.mark.parametrize("text", IDENTICAL)
def test_identical_text_is_exactly_one(text: str) -> None:
    # Regression test: this used to return 0.9999999999999998 for some inputs.
    assert lexical_similarity(text, text) == 1.0
    assert lexical_similarity(text, str(text)) == 1.0


def test_identical_text_exact_even_with_float_unfriendly_counts() -> None:
    text = " ".join(f"w{i % 7}" for i in range(97))
    assert lexical_similarity(text, text) == 1.0


def test_empty_strings() -> None:
    assert lexical_similarity("", "") == 1.0
    assert lexical_similarity("", "text") == 0.0
    assert lexical_similarity("text", "") == 0.0
    assert lexical_similarity("   ", "text") == 0.0
    assert lexical_similarity("  ", "\n") == 1.0


@pytest.mark.parametrize("bad", [None, 1, 1.5, b"bytes", ["a"], {"a": 1}])
def test_invalid_inputs_raise_clear_error(bad: object) -> None:
    with pytest.raises(InvalidInputError, match="must be str"):
        lexical_similarity(bad, "x")  # type: ignore[arg-type]
    with pytest.raises(InvalidInputError):
        lexical_similarity("x", bad)  # type: ignore[arg-type]


def test_range_symmetry_and_ordering() -> None:
    pairs = [("the cat sat", "the cat sat down"), ("alpha beta", "gamma delta"), ("a b c", "c b a")]
    for a, b in pairs:
        s = lexical_similarity(a, b)
        assert 0.0 <= s <= 1.0
        assert s == lexical_similarity(b, a)
    assert lexical_similarity("alpha beta", "gamma delta") == 0.0
    near = lexical_similarity("the cat sat on the mat", "the cat sat on a mat")
    far = lexical_similarity("the cat sat on the mat", "completely different words here")
    assert far < near < 1.0


def test_case_and_whitespace_insensitive_but_punctuation_sensitive() -> None:
    assert lexical_similarity("Hello   World", "hello world") == 1.0
    assert lexical_similarity("Hello!", "Hello") < 1.0


def test_word_order_changes_similarity() -> None:
    assert lexical_similarity("one two three four", "four three two one") < 1.0


def test_input_length_limit() -> None:
    with pytest.raises(InvalidInputError, match="exceeds"):
        lexical_similarity("a" * 1_000_001, "b")


def fake_embedder(texts):
    table = {"cat": [1.0, 0.0], "kitten": [0.9, 0.1], "car": [0.0, 1.0], "neg": [-1.0, 0.0]}
    return [table[t] for t in texts]


def test_embedding_similarity_with_injected_embedder() -> None:
    assert embedding_similarity("cat", "cat", fake_embedder) == 1.0
    close = embedding_similarity("cat", "kitten", fake_embedder)
    assert 0.9 < close < 1.0
    assert embedding_similarity("cat", "car", fake_embedder) == 0.0
    assert embedding_similarity("cat", "neg", fake_embedder) == 0.0  # clamped, never negative


def test_embedding_edge_cases() -> None:
    assert embedding_similarity("", "", fake_embedder) == 1.0
    assert embedding_similarity("", "cat", fake_embedder) == 0.0
    with pytest.raises(InvalidInputError):
        embedding_similarity(None, "cat", fake_embedder)  # type: ignore[arg-type]
    with pytest.raises(InvalidInputError):
        embedding_similarity("cat", "car", lambda t: [[1.0], [1.0, 2.0]])
    with pytest.raises(InvalidInputError):
        embedding_similarity("cat", "car", lambda t: [[float("nan")], [1.0]])
    assert embedding_similarity("cat", "car", lambda t: [[0.0, 0.0], [1.0, 1.0]]) == 0.0


def test_embedding_unavailable_without_extra() -> None:
    default_embedder.cache_clear()
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        with pytest.raises(EmbeddingUnavailableError, match="embeddings"):
            get_similarity_fn("embedding")
    else:  # pragma: no cover - only when the optional extra is installed
        pytest.skip("sentence-transformers installed")


def test_get_similarity_fn() -> None:
    assert get_similarity_fn("lexical") is lexical_similarity
    fn = get_similarity_fn("embedding", embedder=fake_embedder)
    assert fn("cat", "cat") == 1.0
    with pytest.raises(InvalidInputError):
        get_similarity_fn("nope")
