"""Curriculum training CLI for the GATv2 cost model.

Example (from packages/ml-engine):
    PYTHONPATH=src python -m training.train --epochs 60 --out weights/gatv2-demo.pt
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

import torch
from torch import nn

from config import MODEL_DROPOUT, set_seed
from models.checkpoint import ModelConfig, build_model, load_checkpoint, save_checkpoint
from models.gatv2 import parameter_count
from parsers.schema import SchemaCatalog
from training.dataset import (
    PlanGraphDataset,
    apply_edge_dropout,
    concat_datasets,
    make_loader,
)
from training.evaluation import evaluate_model
from training.workload import (
    build_demo_catalog,
    curriculum_tier,
    generate_workload,
)


def _build_datasets(
    catalog: SchemaCatalog,
    per_tier: Sequence[int],
    val_size: int,
    test_size: int,
    seed: int,
) -> tuple[dict[int, PlanGraphDataset], PlanGraphDataset, PlanGraphDataset]:
    tier_datasets: dict[int, PlanGraphDataset] = {}
    for tier, count in enumerate(per_tier, start=1):
        workload = generate_workload(tier, count, seed + tier * 17, catalog)
        tier_datasets[tier] = PlanGraphDataset.from_samples(workload.samples, catalog)
    # Validation mixes all tiers: early stopping must not compare a tier-1 model
    # against tier-3 plans, and the final model must generalise across the
    # curriculum.
    per_tier_val = max(1, val_size // 3)
    validation = concat_datasets(
        *(
            PlanGraphDataset.from_samples(
                generate_workload(
                    tier, per_tier_val, seed + 100 + tier, catalog
                ).samples,
                catalog,
            )
            for tier in (1, 2, 3)
        )
    )
    test = PlanGraphDataset.from_samples(
        generate_workload(3, test_size, seed + 202, catalog).samples, catalog
    )
    return tier_datasets, validation, test


def train(args: argparse.Namespace) -> dict[str, float]:
    set_seed(args.seed)
    catalog = build_demo_catalog()
    tier_datasets, validation, test = _build_datasets(
        catalog,
        per_tier=args.train_per_tier,
        val_size=args.val_size,
        test_size=args.test_size,
        seed=args.seed,
    )

    model_config = ModelConfig(dropout=args.dropout)
    model = build_model(model_config)
    model.to(args.device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.lr, weight_decay=args.weight_decay
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
        optimizer, T_0=10, T_mult=1, eta_min=1e-5
    )
    criterion = nn.HuberLoss(delta=1.0)
    edge_generator = torch.Generator().manual_seed(args.seed)

    validation_loader = make_loader(validation, batch_size=args.batch_size)
    best_score = float("-inf")
    best_metrics: dict[str, float] = {}
    best_epoch = 0
    stale_epochs = 0
    output = Path(args.out)

    print(
        f"model parameters={parameter_count(model)} device={args.device} "
        f"train={[len(tier_datasets[tier]) for tier in (1, 2, 3)]} "
        f"val={len(validation)} test={len(test)}"
    )

    for epoch in range(1, args.epochs + 1):
        tier = curriculum_tier(epoch, args.epochs)
        training = concat_datasets(
            *(tier_datasets[level] for level in range(1, tier + 1))
        )
        loader = make_loader(
            training,
            batch_size=args.batch_size,
            shuffle=True,
            seed=args.seed + epoch,
        )

        model.train()
        running_loss = 0.0
        batches = 0
        for batch in loader:
            batch = batch.to(args.device)
            batch = apply_edge_dropout(batch, args.edge_dropout, edge_generator)
            optimizer.zero_grad()
            prediction = model(batch)
            loss = criterion(prediction, batch.y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            running_loss += float(loss.item())
            batches += 1
        scheduler.step()

        metrics = evaluate_model(model, validation_loader, device=args.device)
        mean_loss = running_loss / max(batches, 1)
        learning_rate = optimizer.param_groups[0]["lr"]
        print(
            f"epoch {epoch:03d}/{args.epochs:03d} tier={tier} "
            f"loss={mean_loss:.4f} val_mae={metrics['mae_ms']:.2f}ms "
            f"val_rmse={metrics['rmse_ms']:.2f}ms rho={metrics['spearman_rho']:.3f} "
            f"lr={learning_rate:.2e}"
        )

        if metrics["spearman_rho"] > best_score:
            best_score = metrics["spearman_rho"]
            best_metrics = metrics
            best_epoch = epoch
            stale_epochs = 0
            save_checkpoint(
                output,
                model,
                model_config,
                metadata={
                    "epoch": epoch,
                    "seed": args.seed,
                    "val_metrics": metrics,
                    "parameters": parameter_count(model),
                    "curriculum": "1-20 simple, 21-50 joins, 51+ complex",
                },
            )
        else:
            stale_epochs += 1
            if args.patience > 0 and stale_epochs >= args.patience:
                print(f"early stopping at epoch {epoch} (best epoch {best_epoch})")
                break

    if not output.exists():
        save_checkpoint(output, model, model_config, metadata={"epoch": args.epochs})

    best_model, _, _ = load_checkpoint(output, map_location=args.device)
    test_metrics = evaluate_model(
        best_model, make_loader(test, batch_size=args.batch_size), device=args.device
    )
    report = {
        "best_epoch": best_epoch,
        "best_val": best_metrics,
        "test": test_metrics,
        "parameters": parameter_count(best_model),
        "seed": args.seed,
        "epochs": args.epochs,
        "model_config": asdict(model_config),
        "dropout": MODEL_DROPOUT,
    }
    metrics_path = output.with_suffix(".metrics.json")
    metrics_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("test metrics:", json.dumps(test_metrics, sort_keys=True))
    print("checkpoint:", output)
    print("metrics:", metrics_path)
    return test_metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train the GATv2 cost model.")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--dropout", type=float, default=MODEL_DROPOUT)
    parser.add_argument("--edge-dropout", type=float, default=0.1)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--train-per-tier", type=int, nargs=3, default=(400, 500, 600)
    )
    parser.add_argument("--val-size", type=int, default=120)
    parser.add_argument("--test-size", type=int, default=200)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--out", default="weights/gatv2-demo.pt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.epochs <= 0:
        raise SystemExit("--epochs must be positive")
    if any(count < 1 for count in args.train_per_tier):
        raise SystemExit("--train-per-tier values must be positive")
    train(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
