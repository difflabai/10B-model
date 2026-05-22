# 10B-model

People not parameters. Modeling the needs of everyone on earth.

The **10B model**: is a 258-country × 15-category satisfaction matrix that flows into
a single human-needs embedding plus three downstream heads
(unsupervised dynamics, supervised trajectory, personal-agent surfaces).

`model.meta.json`, `model.run.json`,
`runs/output.json`, and forecast — can be found under under
[`global/10B/`](./global/10B/).  [the data README](./global/10B/README.md)
describes the artefacts and how the pieces compose.

## Status
Draft

## Repository layout

```
.
├── global/10B/          # The materialised model registry (data).
│   ├── countries/       # 258 country rollups + per-category cells
│   ├── categories/      # 15 category world rollups
│   ├── regions/         # 6 UN-geoscheme regional rollups
│   ├── needs-tree.json  # The schema model that ties categories
│   ├── runs/            # Top-level embedding + manifest outputs
│   └── ...              # See global/10B/README.md
└── scripts/10b/         # The Python pipeline that regenerates global/10B/
```

## Regenerating the initial data

The pipeline is idempotent — re-running on the same input produces the
same output, byte-for-byte. To regenerate:

```sh
# 1. Drop a CIA World Factbook countries dump at the repo root
#    (or point $COUNTRIES_JSON elsewhere).
cp /path/to/cia-factbook-countries.json ./countries.json

# 2. Run the full pipeline (writes back into ./global/10B/).
./scripts/10b/pipeline.sh
```

Each step is also runnable on its own:

| Step | Script | What it produces |
|---|---|---|
| 1 | `generate.py`     | Per-cell + per-rollup `model.meta.json` / `model.run.json` |
| 2 | `scorer.py`       | `runs/output.json` for every cell + country rollups |
| 3 | `extra_models.py` | dynamics / supervised-trajectory / personal-agent models |
| 4 | `dynamics.py`     | k-means cluster assignments + per-country peer lists |
| 5 | `agent_context.py`| Personal-agent connect/contribute/advocate surfaces |
| 6 | `regions.py`      | UN-geoscheme regional rollups |
|   | `forecasts.py`    | Per-rollup forecast.json stubs |
|   | `manifest.py`     | Top-level `runs/manifest.json` summary |
|   | `validate.py`     | Schema validation across every meta + forecast file |

### Pipeline output target

By default, scripts write back into this checkout's `global/10B/`
directory. Override via environment variables:

- `BWM_10B_ROOT` — points at a checkout of this repo (the directory
  containing `global/10B/`). Use this when the script's location and
  the target tree differ — e.g. running pipeline-as-CI against a
  separate worktree.
- `BWM_LOCAL_ROOT` — points at a writable local registry root used by
  the `bwm-server` admin process. Setting this lets a re-run land
  directly in the writable fork without going through a manual import.
- `COUNTRIES_JSON` — absolute path to the CIA Factbook countries dump.
  Defaults to `<repo-root>/countries.json`.

Resolution order is `BWM_10B_ROOT` → `BWM_LOCAL_ROOT` → repo root.

## Consumers

This data feeds into downstream systems that use the 10B model or submodels as inputs. For example
the `business-world-models` admin server, mounts this repo as a
read-only registry and lets users fork all-or-selected models into a
writable local registry via its **Browse Repos** surface.

## License

[MIT](./LICENSE).
