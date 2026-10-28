"""PyG datasets, loaders, and edge dropout for curriculum training."""

from __future__ import annotations

from collections.abc import Sequence

import torch
from torch.utils.data import Dataset
from torch_geometric.data import Data
from torch_geometric.loader import DataLoader

from parsers.explain import plan_to_graph
from parsers.schema import SchemaCatalog
from training.workload import WorkloadSample


class PlanGraphDataset(Dataset[Data]):
    """A list of labelled PyG graphs ready for mini-batching."""

    def __init__(self, graphs: Sequence[Data]) -> None:
        self.graphs: list[Data] = list(graphs)

    @classmethod
    def from_samples(
        cls, samples: Sequence[WorkloadSample], catalog: SchemaCatalog
    ) -> "PlanGraphDataset":
        return cls(
            [
                plan_to_graph(
                    sample.plan,
                    catalog=catalog,
                    execution_time_ms=sample.execution_time_ms,
                ).data
                for sample in samples
            ]
        )

    def __len__(self) -> int:
        return len(self.graphs)

    def __getitem__(self, index: int) -> Data:
        return self.graphs[index]

    @property
    def labels_ms(self) -> list[float]:
        return [
            float(torch.expm1(graph.y.view(-1)[0]).item())
            for graph in self.graphs
            if getattr(graph, "y", None) is not None
        ]


def concat_datasets(*datasets: PlanGraphDataset) -> PlanGraphDataset:
    graphs: list[Data] = []
    for dataset in datasets:
        graphs.extend(dataset.graphs)
    return PlanGraphDataset(graphs)


def split_dataset(
    dataset: PlanGraphDataset, val_size: int, seed: int
) -> tuple[PlanGraphDataset, PlanGraphDataset]:
    if val_size <= 0 or val_size >= len(dataset):
        raise ValueError("val_size must leave at least one training graph")
    generator = torch.Generator().manual_seed(seed)
    indices = torch.randperm(len(dataset), generator=generator).tolist()
    val_indices = indices[:val_size]
    train_indices = indices[val_size:]
    return (
        PlanGraphDataset([dataset.graphs[index] for index in train_indices]),
        PlanGraphDataset([dataset.graphs[index] for index in val_indices]),
    )


def make_loader(
    dataset: PlanGraphDataset,
    batch_size: int = 32,
    shuffle: bool = False,
    seed: int = 0,
) -> DataLoader:
    generator = torch.Generator().manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        generator=generator,
        num_workers=0,
    )


def apply_edge_dropout(
    batch: Data, probability: float, generator: torch.Generator | None = None
) -> Data:
    """Drop edges during training to reduce overfitting to one plan shape."""
    if probability <= 0 or batch.edge_index.size(1) == 0:
        return batch
    keep = torch.rand(batch.edge_index.size(1), generator=generator) >= probability
    if bool(keep.all()):
        return batch
    dropped = batch.clone()
    dropped.edge_index = batch.edge_index[:, keep]
    if getattr(batch, "edge_attr", None) is not None:
        dropped.edge_attr = batch.edge_attr[keep]
    return dropped
