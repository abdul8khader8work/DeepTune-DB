"""Deterministic copilot explainer: turns a run result into streamed prose.

No language model is called. Every sentence is derived from the engine report,
which keeps the copilot offline and honest (a project constraint) while still
streaming token-by-token over the WebSocket for the typing effect the UI wants.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from src.schemas.analysis import AnalysisResult

_MAX_HOTSPOTS = 3


def _ms(value: float) -> str:
    return f"{value:.1f} ms" if value < 10 else f"{value:.0f} ms"


def _reduction(before: float, after: float) -> float:
    if before <= 0:
        return 0.0
    return max(0.0, min(100.0, (before - after) / before * 100.0))


def _hotspots(result: AnalysisResult) -> list[str]:
    if not result.attention:
        return []
    top = sorted(result.attention, key=lambda item: item.weight, reverse=True)[:_MAX_HOTSPOTS]
    parts = []
    for item in top:
        where = f" on {item.relation}" if item.relation else ""
        parts.append(f"{item.operator}{where} ({item.weight:.2f})")
    return parts


def _metric_sentences(result: AnalysisResult) -> list[str]:
    before = float(result.original_metrics.get("time_ms", 0.0))
    after = float(result.optimized_metrics.get("time_ms", 0.0))
    reduction = _reduction(before, after)
    sentences = [
        f"Baseline execution was {_ms(before)}; the optimised estimate is {_ms(after)}, "
        f"a {reduction:.1f}% reduction."
    ]
    if result.speedup_factor > 1.05:
        sentences.append(
            f"The winning beam configuration predicts a {result.speedup_factor:.2f}x speedup."
        )
    return sentences


def _attention_sentences(result: AnalysisResult) -> list[str]:
    hotspots = _hotspots(result)
    if not hotspots:
        return ["No attention weights were recorded for this run."]
    return [
        "GATv2 attention concentrates on " + ", ".join(hotspots) + ".",
        "Those operators dominate the cost model's decision, so an index that "
        "short-circuits them moves the prediction the most.",
    ]


def _recommendation_sentences(result: AnalysisResult) -> list[str]:
    if not result.recommendations:
        return [
            "No index cleared the symbolic filter for this query. The planner "
            "already uses the best available access path."
        ]
    sentences = []
    for index, item in enumerate(result.recommendations, start=1):
        validated = (
            f", hypopg measured {item.validated_speedup_factor:.2f}x"
            if item.validated_speedup_factor
            else ", not yet validated against the shadow database"
        )
        sentences.append(
            f"{index}. {item.sql_statement} — predicted "
            f"{item.predicted_speedup_factor:.2f}x{validated}."
        )
    return sentences


def _risk_sentences(result: AnalysisResult) -> list[str]:
    if not result.recommendations:
        return ["Nothing to apply, so there is no write amplification to weigh."]
    sentences = []
    for item in result.recommendations:
        sentences.append(
            f"{item.target_table}: write amplification +{item.write_impact_percentage:.1f}%, "
            f"storage +{item.storage_overhead_bytes / 1024:.1f} KiB, "
            f"confidence {item.confidence_score * 100:.0f}%."
        )
    sentences.append(
        "DeepTune never applies DDL to your database. The script is emitted as "
        "CREATE INDEX CONCURRENTLY for you to review and run yourself."
    )
    return sentences


def _rejected_sentences(result: AnalysisResult) -> list[str]:
    if not result.rejected_candidates:
        return ["Symbolic pruning rejected no candidates for this query."]
    sentences = [
        f"Pruned {item.description}: {item.reason}."
        for item in result.rejected_candidates[:4]
    ]
    return sentences


def _engine_sentence(result: AnalysisResult) -> str:
    if result.engine == "gnn":
        return (
            f"The neuro-symbolic engine scored {result.symbolic_candidate_count} "
            "symbolic candidate(s) with the GATv2 cost model."
        )
    return (
        "The ML engine was unavailable, so this run used the Phase 2 heuristic "
        "recommender. Numbers are directional, not model predictions."
    )


def summary(result: AnalysisResult) -> list[str]:
    """The opening explanation streamed on connect."""
    sentences = [_engine_sentence(result)]
    sentences.extend(_metric_sentences(result))
    sentences.extend(_attention_sentences(result))
    sentences.extend(_recommendation_sentences(result))
    return sentences


def answer(question: str, result: AnalysisResult) -> list[str]:
    """Route a free-text question to the matching slice of the report."""
    lowered = question.lower()

    if any(token in lowered for token in ("why", "attention", "hotspot", "focus")):
        return _attention_sentences(result)
    if any(token in lowered for token in ("risk", "write", "storage", "safe", "danger")):
        return _risk_sentences(result)
    if any(token in lowered for token in ("reject", "skip", "prune", "why not")):
        return _rejected_sentences(result)
    if any(token in lowered for token in ("index", "sql", "recommend", "create")):
        return _recommendation_sentences(result)
    if any(token in lowered for token in ("slow", "fast", "speed", "latency", "time")):
        return _metric_sentences(result)
    return summary(result)


def chunk(sentences: Sequence[str]) -> list[str]:
    """Split sentences into whitespace-preserving word tokens."""
    tokens: list[str] = []
    for sentence in sentences:
        for word in sentence.split(" "):
            tokens.append(word + " ")
    return tokens


async def stream(sentences: Sequence[str], delay_ms: int) -> AsyncIterator[str]:
    """Yield word tokens with a small delay so the UI can render a typewriter."""
    delay = max(0, delay_ms) / 1000
    for token in chunk(sentences):
        if delay:
            await asyncio.sleep(delay)
        yield token
