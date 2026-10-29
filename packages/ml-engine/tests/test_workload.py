"""Synthetic workload: determinism, curriculum tiers, and parseability."""

from __future__ import annotations

import pytest

from parsers.explain import plan_to_graph
from training.workload import (
    build_demo_catalog,
    curriculum_tier,
    generate_workload,
)


def test_demo_catalog_has_expected_tables() -> None:
    catalog = build_demo_catalog()
    names = {table.name for table in catalog.tables}
    assert names == {"customers", "products", "orders", "order_items", "events"}
    events = catalog.find("events")
    assert events is not None and events.is_write_heavy


@pytest.mark.parametrize("tier", [1, 2, 3])
def test_each_tier_generates_parseable_plans(tier: int) -> None:
    catalog = build_demo_catalog()
    workload = generate_workload(tier, 5, seed=11, catalog=catalog)
    assert len(workload) == 5
    for sample in workload.samples:
        assert sample.tier == tier
        assert sample.execution_time_ms > 0
        graph = plan_to_graph(sample.plan, catalog=catalog)
        assert graph.num_nodes >= 1
        assert graph.label_log is not None


def test_generation_is_deterministic() -> None:
    catalog = build_demo_catalog()
    first = generate_workload(2, 3, seed=42, catalog=catalog)
    second = generate_workload(2, 3, seed=42, catalog=catalog)
    assert [sample.plan for sample in first.samples] == [
        sample.plan for sample in second.samples
    ]
    assert [sample.execution_time_ms for sample in first.samples] == [
        sample.execution_time_ms for sample in second.samples
    ]


def test_curriculum_boundaries() -> None:
    assert curriculum_tier(1, 60) == 1
    assert curriculum_tier(20, 60) == 1
    assert curriculum_tier(21, 60) == 2
    assert curriculum_tier(50, 60) == 2
    assert curriculum_tier(51, 60) == 3
    assert curriculum_tier(60, 60) == 3


def test_curriculum_compresses_for_short_runs() -> None:
    assert curriculum_tier(1, 20) == 1
    assert curriculum_tier(7, 20) == 1
    assert curriculum_tier(8, 20) == 2
    assert curriculum_tier(14, 20) == 2
    assert curriculum_tier(15, 20) == 3
    assert curriculum_tier(20, 20) == 3


@pytest.mark.parametrize("tier", [0, 4, -1])
def test_invalid_tier_raises(tier: int) -> None:
    with pytest.raises(ValueError):
        generate_workload(tier, 1, seed=1)


def test_invalid_count_raises() -> None:
    with pytest.raises(ValueError):
        generate_workload(1, -1, seed=1)
