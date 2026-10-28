"""Packaging for the DeepTune neuro-symbolic ML engine.

The engine is a pure Python library: PyTorch/PyG math, graph parsing, symbolic
pruning, and beam search. It must never import FastAPI, uvicorn, SQLAlchemy, or
database drivers (see AGENTS.md).
"""

from setuptools import find_packages, setup

setup(
    name="deeptune-ml-engine",
    version="0.3.0",
    description="Neuro-symbolic query-plan cost model and index recommender",
    python_requires=">=3.11",
    package_dir={"": "src"},
    packages=find_packages("src"),
    py_modules=["config", "inference"],
    install_requires=[
        "torch>=2.2,<3.0",
        "torch-geometric>=2.5,<3.0",
        "numpy>=1.26,<3.0",
        "sqlglot>=25.0,<30.0",
    ],
    extras_require={"dev": ["pytest>=8.3,<10.0"]},
)
