# IMC Prosperity Engine

Reusable trading engine and research harness for IMC Prosperity.

## Philosophy

This repository is built around a simple idea:

- keep the live trading path thin
- keep the offline research path rich
- encode market logic through explicit modules
- optimize only after correctness and interpretability exist

The architectural principles are defined in [ARCHITECTURE_DOCTRINE.md](/Users/abhinavgupta/Desktop/IMC/ARCHITECTURE_DOCTRINE.md).

## Current Scope

The repository currently contains:

- the architecture doctrine
- the official algorithm guide export
- tutorial research and planning notes
- a reusable project skeleton for the live bot and offline harness
- tutorial CSVs copied into `data/raw/tutorial_round_1`

This is the foundation for building:

1. a production-safe `Trader.run()` engine
2. a replay and review system for tutorial and round data
3. round-specific strategy modules on top of shared core services

## Repository Layout

```text
data/
  raw/
  processed/

docs/
notebooks/

src/
  datamodel.py
  trader.py
  core/
  strategies/
  backtest/
  scripts/

tests/
```

## Development Workflow

Recommended loop:

1. build or refine one core module
2. validate with unit tests
3. replay tutorial data offline
4. inspect logs and review artifacts
5. only then tune strategy parameters

## Quick Start

Create a virtual environment, install dependencies, and run the smoke checks:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
python -m src.scripts.validate_submission
python -m src.scripts.run_backtest
```

## Important Files

- [ARCHITECTURE_DOCTRINE.md](/Users/abhinavgupta/Desktop/IMC/ARCHITECTURE_DOCTRINE.md)
- [Writing an Algorithm in Python.html](/Users/abhinavgupta/Desktop/IMC/Writing%20an%20Algorithm%20in%20Python.html)
- [Implementation Plan.md](/Users/abhinavgupta/Desktop/IMC/Tutorial/Implementation%20Plan.md)
- [Manual Strategy Plan.md](/Users/abhinavgupta/Desktop/IMC/Tutorial/Manual%20Strategy%20Plan.md)
- [deep-research-report.md](/Users/abhinavgupta/Desktop/IMC/Tutorial/deep-research-report.md)

