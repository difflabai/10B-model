---
name: simulation
description: Run the Monte Carlo simulation for one milestone question under one scenario and return a numeric prediction with explicit eighty percent intervals.
allowed_tools:
  - Bash
inputs:
  scenario: One of eli, daniel, alex, brendan
  milestone: One of ac, sar, siar, ted_ai, asi
  parameters: ParameterSnapshot — see REFERENCE.md
  num_samples: integer; default ten thousand
  seed: integer
outputs:
  prediction: numeric prediction with mean and intervals
  manifest: simulation manifest with seed, draws, derived intermediates
---

# Simulation skill

The simulation engine lives next to this file as `simulation.py`. The base agent invokes it via the Bash tool with stdin JSON of the form:

```
{"scenario": "eli", "milestone": "ac", "parameters": {...}, "num_samples": 10000, "seed": 42}
```

and reads stdout JSON containing the typed prediction plus a manifest of parameter draws and derived intermediate variables. The engine implements the staged formula across the three regimes from the source model, the takeoff dynamics governed by the ratio-of-doublings parameter, the taste-only-singularity conditional, and the interpolation method between the current state and the Automated Coder threshold.

The engine is reproducible: invoking it with the same scenario, milestone, parameter snapshot, and seed produces an identical numeric prediction and manifest. The frozen-parameters reproducibility test relies on this property to verify that revisions to the simulation skill do not silently change behaviour.

When the harness editor proposes changes to `simulation.py`, the structural validator runs `python3 -m py_compile` plus the embedded reproducibility test before the promoter accepts the new version.
