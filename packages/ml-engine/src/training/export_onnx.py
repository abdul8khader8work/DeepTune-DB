"""Export a trained GATv2 checkpoint to ONNX for onnxruntime inference.

Example (from packages/ml-engine):
    PYTHONPATH=src python -m training.export_onnx \
        --checkpoint weights/demo-final.pt --out weights/demo-final.onnx

The export is verified against the PyTorch forward before the file is kept: a
parity drift above ``1e-3`` deletes the artifact and fails the command, so a
broken ONNX graph can never be shipped.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from models.checkpoint import load_checkpoint
from models.onnx import OnnxModelScorer, export_onnx
from parsers.explain import plan_to_graph
from training.workload import build_demo_catalog, generate_workload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a GATv2 checkpoint to ONNX.")
    parser.add_argument("--checkpoint", default="weights/demo-final.pt")
    parser.add_argument("--out", default="")
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--tier", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the torch-vs-onnx parity gate (not recommended)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checkpoint = Path(args.checkpoint)
    destination = Path(args.out) if args.out else checkpoint.with_suffix(".onnx")

    model, config, metadata = load_checkpoint(checkpoint)
    catalog = build_demo_catalog()
    sample = generate_workload(args.tier, 1, seed=args.seed, catalog=catalog).samples[0]
    graph = plan_to_graph(sample.plan, catalog=catalog)

    export_onnx(
        model,
        destination,
        graph.data,
        config,
        metadata,
        verify=not args.no_verify,
        opset=args.opset,
    )

    scorer = OnnxModelScorer(destination)
    timings = scorer.benchmark([graph], repeats=25)
    summary = {
        "checkpoint": str(checkpoint),
        "onnx": str(destination),
        "bytes": destination.stat().st_size,
        "opset": args.opset,
        "metadata": scorer.metadata,
        "verified": not args.no_verify,
        "benchmark": timings,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
