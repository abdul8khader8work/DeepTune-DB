"""Evaluate a trained checkpoint on a held-out synthetic workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from models.checkpoint import load_checkpoint
from models.gatv2 import parameter_count
from training.dataset import PlanGraphDataset, make_loader
from training.evaluation import evaluate_model
from training.workload import build_demo_catalog, generate_workload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate a GATv2 checkpoint.")
    parser.add_argument("--checkpoint", default="weights/gatv2-demo.pt")
    parser.add_argument("--tier", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=999)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--out", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    model, config, metadata = load_checkpoint(args.checkpoint, map_location=args.device)
    catalog = build_demo_catalog()
    workload = generate_workload(args.tier, args.size, args.seed, catalog)
    dataset = PlanGraphDataset.from_samples(workload.samples, catalog)
    loader = make_loader(dataset, batch_size=args.batch_size)
    metrics = evaluate_model(model, loader, device=args.device)
    report = {
        "checkpoint": str(Path(args.checkpoint)),
        "tier": args.tier,
        "samples": len(dataset),
        "parameters": parameter_count(model),
        "trained_epoch": metadata.get("epoch"),
        "metrics": metrics,
    }
    payload = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
