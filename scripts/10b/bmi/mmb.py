"""MMB (Macroeconomic Model Data Base) Modelbase-block compatibility.

The MMB convention (IMFS, Goethe University Frankfurt) lets any model be
simulated under a common monetary policy rule, because every conformant
model exposes the same five "common variables" and a single swappable
policy block. It is a *profile on top of BMI*: BMI standardises the
runtime; the MMB block adds a semantic contract (these five named
variables mean these economic quantities) plus a structural seam (the
policy rule can be replaced).

`MmbCompliantBmi` is a mixin a 10B BMI node adds when it is genuinely
macroeconomic (the FRB/US wrapper, and the US country rollup it backs).
The node's `model.run.json` carries an `mmb` block:

    "mmb": {
      "capabilities": ["TAYLOR", "SW", "MODEL_SPECIFIC"],
      "common_variables": { "interest": "monetary_policy__short_rate_annualized", ... },
      "policy_rule": { "rule_id": "MODEL_SPECIFIC", "msr": null }
    }

The mixin reads that block on `initialize` and exposes the MMB query +
policy-swap API. The 33-coefficient `msr` array follows MMB's documented
convention verbatim (annual interest-shock std-dev 1, quarterly 0.25).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from . import standard_names as _sn

# The MMB common monetary policy rules + the model-specific sentinel.
MMB_RULE_VALUES = {
    "TAYLOR", "SW", "CMR", "CGG", "OW06", "OW08", "LWW03", "CEE", "GR07",
    # FRB/US ships its own named rule variants, accepted as capabilities too.
    "TAYLOR_LWW", "TAYLOR_INERTIAL", "MC_TAYLOR_INERTIAL", "TAYLOR_INTERCEPT",
    "MODEL_SPECIFIC",
}

# The five MMB common-variable short names (must all be present in an
# mmb.common_variables map).
MMB_COMMON_NAMES = {"interest", "inflation", "inflationq", "outputgap", "output"}

# Canonical short→long mapping for the five common variables, plus shocks.
MMB_COMMON = dict(_sn.MMB_ALIASES)  # includes 'fispol'
MMB_FISPOL = _sn.MMB_FISPOL_ALIAS   # "fiscal_"
MMB_INTSHK = _sn.MMB_INTSHK_ALIAS   # "interest_"

# Number of coefficients in the standardised MMB policy-rule (msr) array.
MMB_MSR_LEN = 33


class MmbCompliantBmi:
    """Mixin adding the MMB Modelbase-block surface to a `Bmi10BBase` node.

    Expects the host class to provide `self._run` (loaded on initialize).
    A conformant host must declare the five MMB common variables among its
    `OUTPUT_VARS` (validated by `validate.py`).
    """

    def _mmb_block(self) -> dict:
        return getattr(self, "_run", {}).get("mmb", {}) or {}

    def is_mmb_compliant(self) -> bool:
        return bool(self._mmb_block())

    def get_mmb_capabilities(self) -> List[str]:
        """Policy rules this model can be simulated under."""
        return list(self._mmb_block().get("capabilities", []))

    def has_model_specific_rule(self) -> bool:
        return "MODEL_SPECIFIC" in self.get_mmb_capabilities()

    def get_mmb_common_variables(self) -> Dict[str, str]:
        """Map of MMB short name → 10B long standard name for this node."""
        return dict(self._mmb_block().get("common_variables", {}))

    def get_policy_rule(self) -> Tuple[str, Optional[np.ndarray]]:
        """Return the current (rule_id, msr-coefficients) policy rule."""
        block = self._mmb_block().get("policy_rule", {})
        rule_id = block.get("rule_id", "MODEL_SPECIFIC")
        msr = block.get("msr")
        coeffs = np.asarray(msr, dtype="float64") if msr is not None else None
        # Allow a runtime override set via set_policy_rule.
        override = getattr(self, "_policy_rule_override", None)
        if override is not None:
            return override
        return rule_id, coeffs

    def set_policy_rule(
        self, rule_id: str, coefficients: Optional[np.ndarray] = None
    ) -> None:
        """Replace the policy block for the next `update()`.

        `rule_id` must be a declared capability (or MODEL_SPECIFIC).
        `coefficients` is an optional 33-entry MMB `msr` array.
        """
        caps = set(self.get_mmb_capabilities()) | {"MODEL_SPECIFIC"}
        if rule_id not in caps:
            raise ValueError(
                f"rule {rule_id!r} not in capabilities {sorted(caps)}"
            )
        coeffs = None
        if coefficients is not None:
            coeffs = np.asarray(coefficients, dtype="float64")
            if coeffs.size != MMB_MSR_LEN:
                raise ValueError(
                    f"msr must have {MMB_MSR_LEN} coefficients, got {coeffs.size}"
                )
        self._policy_rule_override = (rule_id, coeffs)
        # Subclasses that need to re-wire a backing solver override this hook.
        self._on_policy_rule_changed(rule_id, coeffs)

    def _on_policy_rule_changed(
        self, rule_id: str, coefficients: Optional[np.ndarray]
    ) -> None:
        """Hook: a backing-model node (FRB/US) re-points its solver here."""
        # Default: no-op; the override is read in get_policy_rule / _compute.
        return None


def mmb_block_errors(mmb: dict, output_var_names: Optional[set] = None) -> List[str]:
    """Validate an `mmb` block. Used by validate.py.

    Checks capabilities ⊆ MMB_RULE_VALUES, common_variables keys equal the
    five MMB names and resolve to registered standard names, and the
    policy_rule.rule_id is a declared capability (or MODEL_SPECIFIC). When
    `output_var_names` is supplied, also checks the five common variables
    are covered by the node's outputs.
    """
    errs: List[str] = []
    if not isinstance(mmb, dict):
        return ["mmb must be an object"]

    caps = mmb.get("capabilities")
    if not isinstance(caps, list) or not caps:
        errs.append("mmb.capabilities must be a non-empty list")
    else:
        bad = [c for c in caps if c not in MMB_RULE_VALUES]
        if bad:
            errs.append(f"mmb.capabilities has unknown rule(s): {bad}")

    common = mmb.get("common_variables")
    if not isinstance(common, dict):
        errs.append("mmb.common_variables must be an object")
    else:
        if set(common.keys()) != MMB_COMMON_NAMES:
            errs.append(
                f"mmb.common_variables keys must be exactly {sorted(MMB_COMMON_NAMES)}; "
                f"got {sorted(common.keys())}"
            )
        for short, long in common.items():
            if not _sn.is_registered(long):
                errs.append(f"mmb.common_variables[{short}] not a registered name: {long}")
        if output_var_names is not None:
            missing = {
                long for long in common.values() if long not in output_var_names
            }
            if missing:
                errs.append(
                    f"mmb common variables not in node outputs: {sorted(missing)}"
                )

    rule = mmb.get("policy_rule", {})
    if not isinstance(rule, dict):
        errs.append("mmb.policy_rule must be an object")
    else:
        rid = rule.get("rule_id")
        allowed = set(caps or []) | {"MODEL_SPECIFIC"}
        if rid not in allowed:
            errs.append(f"mmb.policy_rule.rule_id {rid!r} not in {sorted(allowed)}")
        msr = rule.get("msr")
        if msr is not None:
            if not isinstance(msr, list) or len(msr) != MMB_MSR_LEN:
                errs.append(f"mmb.policy_rule.msr must be {MMB_MSR_LEN} numbers or null")
    return errs


def build_mmb_block(
    capabilities: List[str],
    rule_id: str = "MODEL_SPECIFIC",
    msr: Optional[List[float]] = None,
) -> dict:
    """Construct a canonical `mmb` block for a `model.run.json`."""
    return {
        "capabilities": list(capabilities),
        "common_variables": {short: MMB_COMMON[short] for short in
                             ("interest", "inflation", "inflationq",
                              "outputgap", "output")},
        "policy_rule": {"rule_id": rule_id, "msr": msr},
    }


# Capabilities inherited by a country rollup from its macro backing model.
# A US rollup backed by FRB/US can be simulated under FRB/US's rule set.
BACKED_COUNTRY_CAPABILITIES = [
    "TAYLOR_LWW", "TAYLOR_INERTIAL", "MC_TAYLOR_INERTIAL",
    "TAYLOR_INTERCEPT", "MODEL_SPECIFIC",
]


def mmb_block_for(model_id: str) -> Optional[dict]:
    """Return the `mmb` block for a node that should be MMB-compliant, or
    None. Single source of truth shared by the generators and the backfill
    so a regenerated tree and a backfilled tree agree.

    Currently: the country rollups of MMB-backed countries (the US, backed
    by FRB/US). The external FRB/US node builds its own block in
    `frbus_node.py`.
    """
    from .classmap import MMB_BACKED_COUNTRIES

    parts = model_id.split(".")
    if (
        model_id.startswith("global.10B.countries.")
        and len(parts) == 4
        and parts[3] in MMB_BACKED_COUNTRIES
    ):
        return build_mmb_block(BACKED_COUNTRY_CAPABILITIES)
    return None
