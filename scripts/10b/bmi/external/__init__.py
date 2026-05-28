"""BMI wrappers for external macroeconomic models.

These nodes wrap models maintained outside the 10B project (currently the
Federal Reserve's FRB/US). Their runtimes are optional, never bundled, and
imported lazily — a 10B checkout without them still introspects, validates,
and runs the rest of the pipeline.
"""
