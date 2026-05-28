"""PersonalAgentBmi — the agent-facing query head.

Produces the connect / contribute / advocate surfaces for every country.
These are string-typed outputs: BMI's numeric `get_value` cannot carry
them, so they are advertised with type "str" and served through the 10B
`get_value_text` extension.
"""

from __future__ import annotations

from .base import Bmi10BBase
from . import grids as _grids


class PersonalAgentBmi(Bmi10BBase):
    COMPONENT_NAME = "personal-agent surfaces"

    INPUT_VARS = ("population_needs__satisfaction_score",)
    OUTPUT_VARS = (
        "population_agent__connect_surface_text",
        "population_agent__contribute_surface_text",
        "population_agent__advocate_surface_text",
    )

    def _grid_for(self, name: str) -> int:
        # One surface per country.
        return _grids.COUNTRY_POINTS

    def _compute(self) -> None:
        # The agent head materialises one file per country (runs/<slug>.json)
        # plus a runs/index.json listing them; the connect/contribute/advocate
        # text lives in the per-country files.
        if self._model_dir is None:
            return
        index = self._read_output("runs/index.json")
        by_country = index.get("by_country")
        slugs = list(by_country.keys()) if isinstance(by_country, dict) else []
        connect, contribute, advocate = {}, {}, {}
        for slug in slugs:
            rec = self._read_output(f"runs/{slug}.json")
            if not rec:
                continue
            connect[slug] = rec.get("connect")
            contribute[slug] = rec.get("contribute")
            advocate[slug] = rec.get("advocate")
        if connect:
            self._text_values["population_agent__connect_surface_text"] = connect
            self._text_values["population_agent__contribute_surface_text"] = contribute
            self._text_values["population_agent__advocate_surface_text"] = advocate
