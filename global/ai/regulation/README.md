# /global/ai/regulation/

AI regulatory-environment models for the **United States** and **China**,
as of 2026-10-27. Closed-form engine (`bwm-engine-closed-form`).

```
regulation/
  equations.json          # ONE graph, shared by every jurisdiction
  instruments.json        # sourced catalogue of the laws each slot aggregates (data, not a run input)
  us/
    model.run.json        # baseline run
    model.meta.json
    params/baseline.json
    params/federal-preemption.json
    forecasts/*.json
  china/
    model.run.json
    model.meta.json
    params/baseline.json
    params/import-thaw.json
    params/ai-law.json
    forecasts/*.json
```

## Design

**One graph, many bindings.** A jurisdiction is a params file. It is never a
separate equation set. That keeps US and China outputs commensurable, and it
means a scenario (preemption, an AI Law, a customs thaw) rebinds leaves without
reshaping anything. A third jurisdiction (EU, UK) is a new `params/` directory.

**Six instrument slots.** Every AI-relevant instrument maps to one slot:

| slot | what it covers | US anchor | China anchor |
|---|---|---|---|
| `frontier` | frontier-model safety, transparency, incident reporting | CA SB 53, NY RAISE | AI Safety Governance Framework 2.0 (soft law) |
| `highrisk` | use-specific / consequential-decision duties | Colorado AI Act, IL HB 3773, NYC LL144, TRAIGA, CCPA ADMT | algorithm-recommendation provisions, anthropomorphic-interaction measures, PIPL Art. 24 |
| `filing` | ex-ante approval or registration before launch | FDA device review only | CAC generative-AI filing + algorithm registry |
| `content` | labeling, provenance, takedown, synthetic media | TAKE IT DOWN, CA SB 942 / SB 243 | Labeling Measures + GB 45438-2025, deep synthesis |
| `data` | personal data, data security, cross-border | state privacy laws, DOJ bulk-data rule | PIPL, DSL, 2025 network-data regs, 2026 CSL amendment |
| `trade` | export controls borne by domestic AI firms | BIS advanced-computing controls, H200 case-by-case | tech-export catalogue, rare-earth controls |

Each slot is `coverage × cost_share × p_in_force × p_enforced`, where
`coverage` is the share of AI revenue in scope and `cost_share` is the annual
compliance cost per unit of in-scope revenue. Instruments that set posture and
impose no duty of their own (EO 14179, EO 14365, AI+, the informal H200 customs
block) are catalogued with `slot: null`. They act through `p_in_force`,
`state_support` or `compute` instead.

**Outputs that matter.**

- `gross_burden` / `net_burden` is the expected annual regulatory cost as a
  share of the reference firm's AI revenue. It has three parts: variable
  (slots), fixed (the patchwork: regimes × fixed cost / revenue), and delay (the
  ex-ante gate's months × obsolescence). `net_burden` subtracts state support.
- `contested_share` is the share of the cost at stake whose legal status is
  unsettled, weighted `4·p·(1−p)`. It is the uncertainty a firm cannot price.
- `enforcement_gap` is the share of obligations in force that are not enforced
  in expectation.
- `compute_access` is `min(1, domestic + licensed × realised + grey)`. It uses a
  binding `min` rather than a smooth surrogate, so oversupply is slack, not extra
  access.

## Baseline readings

| output | US | US preemption | China | China import-thaw | China AI Law |
|---|---:|---:|---:|---:|---:|
| gross_burden | 4.8% | 2.9% | 15.8% | 15.8% | 16.2% |
| net_burden | 3.8% | 1.9% | 11.8% | 11.8% | 12.2% |
| ↳ fixed (patchwork) | 2.4% | 0.6% | 0.6% | 0.6% | 0.6% |
| ↳ ex-ante delay | 0.6% | 0.6% | 11.8% | 11.8% | 11.8% |
| gate delay (months) | 0.15 | 0.15 | 2.83 | 2.83 | 2.83 |
| contested_share | 36% | 24% | 19% | 19% | 16% |
| compute_access | 1.00 | 1.00 | 0.67 | 0.86 | 0.67 |

What the table says:

1. **The US cost is the patchwork plus uncertainty, not compliance spend.**
   Half of gross burden is the fixed cost of mapping about 12 regimes, and 36% of
   the cost at stake is legally contested. Preemption is a fixed-cost reform.
   Because fixed costs are regressive, it helps small firms most.
2. **The China cost is the gate.** The CAC launch delay outweighs every
   compliance slot combined. This result rests on one leaf,
   `ex_ante_gate.obsolescence_per_year` (0.5). If it is halved, China's
   gross burden falls to about 10%. Treat it as the first thing to calibrate.
3. **Most of China's compute gap is self-imposed.** Raising only Beijing's
   import-realisation rate closes about 56% of the gap. US licensing policy now
   matters less than Chinese industrial policy.
4. **An AI Law barely moves China.** Filing and labeling are already
   statute-grade. A general law would mostly harden the soft-law frontier
   framework.

## Authority

Every leaf is an **authored prior**. Each one is a sourced judgement whose
basis sits inline in the params file, and none of them is fitted. Read the
outputs as structure ("where the cost comes from, and what moves it"), not as
measured cost levels. The `confidence` field in `instruments.json` grades the
catalogue entry, not the law. `low` and `medium` entries come from secondary
trackers and need checking against primary text before anything is graded
against them.

## Running

```sh
# from a business-world-models checkout, with BWM_10B_ROOT pointing here
cargo test -p bwm-engine-core --test nexus_verification every_model_run_json_under_global_loads
```

The `global/ai` namespace is in `ENGINE_NAMESPACES`, so both contracts are
loaded by that walk. A scenario run copies `model.run.json` and re-points
`inputs.params.path` and `output`.
