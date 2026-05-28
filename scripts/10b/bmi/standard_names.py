"""CSDMS-style Standard Names for the 10B model.

CSDMS standard names follow `object__quantity` (e.g.
`land_surface__elevation`). No existing CSDMS name covers human-needs or
social indicators, so 10B defines its own namespaces:

  - population_*        the human-needs core (scores, embeddings, coverage)
  - monetary_policy__*  } the MMB / macroeconomic surface, used by the
  - consumer_prices__*  } macro nodes and the FRB/US wrapper. These align
  - national_accounts__*} with the MMB "common variables" via MMB_ALIASES
  - labour_market__*    } so a model that speaks the short MMB names
  - fiscal_policy__*     } (interest/inflation/...) and one that speaks the
                          long CSDMS names get the same data.

Each name carries a dtype, a udunits-style unit string (`"1"` for
dimensionless), and an `external` flag. `external` names are produced by a
model outside the 10B registry (e.g. FRB/US); the standard-name-closure
validator treats them as satisfied without an in-registry producer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class StandardName:
    name: str
    dtype: str  # numpy dtype string: float64 / int32 / int8 / str
    units: str  # udunits string; "1" for dimensionless
    description: str
    external: bool = False  # produced outside the 10B registry


def _sn(name, dtype, units, description, external=False) -> StandardName:
    return StandardName(name, dtype, units, description, external)


# --- The population_* core ------------------------------------------------
_CORE = [
    _sn("population_needs__satisfaction_score", "float64", "1",
        "Composite needs-satisfaction score in [0,1]."),
    _sn("population_needs__category_embedding", "float64", "1",
        "Per-category 16-dim embedding feeding the macro space."),
    _sn("population_needs__country_embedding", "float64", "1",
        "Country-level needs embedding spanning all 15 categories."),
    _sn("population_needs__macro_embedding", "float64", "1",
        "The 10B macro human-needs embedding."),
    _sn("population_needs__indicator_coverage", "float64", "1",
        "Fraction of category indicators with non-null values."),
    _sn("population_needs__tier_score", "float64", "1",
        "Per-tier (subsistence/development/agency) satisfaction average."),
    _sn("population_demographics__population", "float64", "persons",
        "Total population of the country."),
    _sn("population_demographics__life_expectancy", "float64", "a",
        "Life expectancy at birth, years."),
    _sn("population_demographics__fertility_rate", "float64", "1",
        "Total fertility rate, births per woman."),
    _sn("population_demographics__internet_penetration", "float64", "1",
        "Share of population using the internet."),
    _sn("population_economics__gdp_per_capita", "float64", "USD",
        "GDP per capita, USD per person."),
    _sn("population_economics__gini", "float64", "1",
        "Gini coefficient of income inequality."),
    _sn("population_dynamics__cluster_id", "int32", "1",
        "k-means cluster assignment for a country."),
    _sn("population_dynamics__cluster_centroid_embedding", "float64", "1",
        "Embedding of a dynamics cluster centroid."),
    _sn("population_dynamics__peer_country_indices", "int32", "1",
        "Indices of a country's nearest peers."),
    _sn("population_dynamics__ranking_index", "int32", "1",
        "Rank position of a country on a category."),
    _sn("population_dynamics__ranking_score", "float64", "1",
        "Score backing a country's category rank."),
    _sn("population_supervised__quintile_prediction", "int8", "1",
        "Predicted sociodemographic quintile, hold-out target."),
    _sn("population_supervised__holdout_auc", "float64", "1",
        "Hold-out AUC of the supervised quintile classifier."),
    _sn("population_agent__connect_surface_text", "str", "1",
        "Personal-agent 'connect with neighbours' surface."),
    _sn("population_agent__contribute_surface_text", "str", "1",
        "Personal-agent 'economic contribution' surface."),
    _sn("population_agent__advocate_surface_text", "str", "1",
        "Personal-agent 'advocate for change' surface."),
    _sn("population_forecast__expected_score", "float64", "1",
        "Expected value of a forecast at its horizon."),
    _sn("population_forecast__resolved_score", "float64", "1",
        "Resolved value of a forecast once its date passes."),
    _sn("schema__needs_tree", "str", "1",
        "The canonical needs-tree schema document."),
    _sn("model_run__data_vintage_iso", "str", "1",
        "ISO date stamp of the data this model run consumed."),
]

# --- The MMB / macroeconomic surface --------------------------------------
# The five MMB common variables (long CSDMS form) plus the two MMB shocks
# and the supporting macro series the FRB/US wrapper supplies. The macro
# series are `external` until a backing model (FRB/US) is installed.
_MACRO = [
    _sn("monetary_policy__short_rate_annualized", "float64", "1",
        "Annualised short-term policy interest rate, percent. (MMB: interest)"),
    _sn("monetary_policy__rule_shock", "float64", "1",
        "Monetary policy rule shock. (MMB: interest_)", external=True),
    _sn("consumer_prices__inflation_yoy_pct", "float64", "1",
        "Year-on-year inflation, percent. (MMB: inflation)"),
    _sn("consumer_prices__inflation_qoq_annualized", "float64", "1",
        "Annualised quarter-on-quarter inflation, percent. (MMB: inflationq)"),
    _sn("national_accounts__output_gap_pct", "float64", "1",
        "Output gap, percent of potential. (MMB: outputgap)"),
    _sn("national_accounts__output_level_index", "float64", "1",
        "Output level index. (MMB: output)"),
    _sn("national_accounts__consumption_index", "float64", "1",
        "Real consumption index.", external=True),
    _sn("labour_market__unemployment_rate_pct", "float64", "1",
        "Unemployment rate, percent.", external=True),
    _sn("labour_market__nairu_pct", "float64", "1",
        "Natural rate of unemployment, percent.", external=True),
    _sn("fiscal_policy__discretionary_shock", "float64", "1",
        "Discretionary fiscal policy shock. (MMB: fispol)", external=True),
    _sn("fiscal_policy__federal_spending_index", "float64", "1",
        "Federal government spending index.", external=True),
    _sn("foreign_sector__world_gdp", "float64", "1",
        "Foreign / world GDP aggregate.", external=True),
    _sn("commodity_markets__crude_oil_price", "float64", "USD",
        "Crude oil price, USD per barrel.", external=True),
    _sn("aggregate_demand__shock", "float64", "1",
        "Aggregate demand shock.", external=True),
]

STANDARD_NAMES: Dict[str, StandardName] = {
    sn.name: sn for sn in (_CORE + _MACRO)
}

# The five MMB common variables: short MMB name -> long CSDMS name. A
# consumer can address a variable by either; `resolve` follows the alias.
MMB_ALIASES: Dict[str, str] = {
    "interest": "monetary_policy__short_rate_annualized",
    "inflation": "consumer_prices__inflation_yoy_pct",
    "inflationq": "consumer_prices__inflation_qoq_annualized",
    "outputgap": "national_accounts__output_gap_pct",
    "output": "national_accounts__output_level_index",
    "fispol": "fiscal_policy__discretionary_shock",
}

# The MMB monetary-policy shock and fiscal shock, by their MMB short names.
MMB_INTSHK_ALIAS = "interest_"
MMB_FISPOL_ALIAS = "fiscal_"
_SHOCK_ALIASES = {
    MMB_INTSHK_ALIAS: "monetary_policy__rule_shock",
    MMB_FISPOL_ALIAS: "fiscal_policy__discretionary_shock",
}

# The set of standard names that are produced outside the 10B registry.
EXTERNAL_NAMES = {sn.name for sn in STANDARD_NAMES.values() if sn.external}


def resolve(name: str) -> str:
    """Follow an MMB short alias to its canonical long standard name. A
    name that is already canonical (or unknown) is returned unchanged.
    """
    if name in MMB_ALIASES:
        return MMB_ALIASES[name]
    if name in _SHOCK_ALIASES:
        return _SHOCK_ALIASES[name]
    return name


def get(name: str) -> StandardName:
    """Look up a standard name, following MMB aliases. Raises KeyError with
    a clear message for an unregistered name.
    """
    canonical = resolve(name)
    if canonical not in STANDARD_NAMES:
        raise KeyError(
            f"unknown standard name: {name!r} (resolved to {canonical!r}); "
            f"register it in standard_names.py"
        )
    return STANDARD_NAMES[canonical]


def is_registered(name: str) -> bool:
    return resolve(name) in STANDARD_NAMES
