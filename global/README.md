# /global/

Reusable models that are not scoped to a single company, market, or
world artifact. Each model lives at a stable path; downstream consumers
(BWM forecast service, sector rollups, agents) reference it by that
path.

Layout:

- `economic/` — sectoral and macro-economic models.
- `ai/` — AI-progress / capability-trajectory models.

Every model directory contains a `model.run.json` describing how a
generic engine should run it. Today the BWM workspace ships two
engines:

- **closed-form** (`bwm-engine-closed-form`): evaluates an
  `equations.json` spec against named scalar inputs. Used by
  `economic/layoff-trap/`.
- **monte-carlo** (`bwm-engine-monte-carlo`): spawns `python3` against
  a script directory, passing inputs on stdin and reading the
  prediction back on stdout. Used by `ai/aifutures/`.

Adding a new model is purely VFS work: drop a `model.run.json`, the
engine-specific spec (an equations file, or a simulation directory),
and any input artifacts. No new Rust crates are needed for models
that fit one of the existing engines.
