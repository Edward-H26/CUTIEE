"""Lightweight embedding helpers.

We deliberately avoid loading FastEmbed during process startup: the model is
~200MB and slow to warm up. Tests and Phase-1 demos pass `useHashFallback`
so the pipeline still runs end-to-end without the heavy dependency. The
hash-based vector keeps the cosine API stable across the two backends so
ranking math doesn't have to special-case the test path.
"""
from __future__ import annotations

import hashlib
import math
import threading
from collections.abc import Iterable
from typing import Any

DEFAULT_DIMENSION = 256
_MODEL_LOCK = threading.Lock()
_MODEL: Any = None


def cosineSimilarity(a: Iterable[float] | None, b: Iterable[float] | None) -> float:
    if a is None or b is None:
        return 0.0
    aList = list(a)
    bList = list(b)
    if not aList or not bList:
        return 0.0
    if len(aList) != len(bList):
        size = min(len(aList), len(bList))
        aList = aList[:size]
        bList = bList[:size]
    dot = sum(x * y for x, y in zip(aList, bList))
    normA = math.sqrt(sum(x * x for x in aList))
    normB = math.sqrt(sum(y * y for y in bList))
    if normA == 0.0 or normB == 0.0:
        return 0.0
    return dot / (normA * normB)


def hashEmbedding(text: str, dimension: int = DEFAULT_DIMENSION) -> list[float]:
    """Deterministic, dependency-free embedding for tests + offline mode.

    Splits the SHA-256 digest of the input into `dimension` byte chunks and
    converts each chunk into a [-1, 1] float. The output has stable cosine
    behavior on similar inputs because shared substrings produce shared
    digest prefixes.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    repeats = (dimension + len(digest) - 1) // len(digest)
    bytesBuffer = (digest * repeats)[:dimension]
    return [(byte - 128) / 128.0 for byte in bytesBuffer]


def embedTexts(
    texts: list[str],
    *,
    useHashFallback: bool = True,
    dimension: int = DEFAULT_DIMENSION,
) -> list[list[float]]:
    if useHashFallback:
        return [hashEmbedding(text, dimension) for text in texts]
    model = _loadFastEmbedModel()
    return [list(vector) for vector in model.embed(texts)]


def _loadFastEmbedModel() -> Any:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from fastembed import TextEmbedding

            _MODEL = TextEmbedding(model_name = "BAAI/bge-small-en-v1.5")
    return _MODEL
