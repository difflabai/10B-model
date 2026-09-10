#!/usr/bin/env python3
"""Adapter from the generic bwm-engine-monte-carlo envelope
({"inputs": {...}, "iterations": <int|null>}) to simulation.py's
historical stdin shape ({"scenario", "milestone", "parameters",
"num_samples", "seed"}). Keeps simulation.py content-hash-stable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def main() -> int:
    payload = json.load(sys.stdin)
    inputs = payload.get("inputs") or {}
    iterations = payload.get("iterations")
    if iterations is not None and "num_samples" not in inputs:
        inputs = dict(inputs)
        inputs["num_samples"] = int(iterations)

    here = os.path.dirname(os.path.abspath(__file__))
    sim = os.path.join(here, "simulation.py")
    res = subprocess.run(
        [sys.executable, sim],
        input=json.dumps(inputs).encode(),
        capture_output=True,
    )
    sys.stderr.buffer.write(res.stderr)
    if res.returncode != 0:
        return res.returncode
    sys.stdout.buffer.write(res.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
