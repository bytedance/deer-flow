---
name: site-wind-snow-lookup
description: Use this skill when the user needs a region's wind pressure and snow pressure for iCAD structural load context. It queries bundled GB50009 city data first, then tells the agent to search the web, and finally ask the user when the location is still unresolved.
---

# Site Wind Snow Lookup

Use this skill to retrieve wind pressure and snow pressure for a project region.

## Workflow

1. Run the bundled script with the user region, for example `python scripts/query_wind_snow.py 北京市`.
2. If the script returns `status: "found"`, use the returned `wind_pressure_kN_per_m2` and `snow_pressure_kN_per_m2`.
3. If the script returns `status: "ambiguous"`, ask the user for a more specific region before making load assumptions.
4. If the script returns `status: "not_found"`, search the web for the region's wind pressure and snow pressure.
5. If web results are still missing, conflicting, or low-confidence, ask the user to provide a more specific region or the design basis directly.

## Notes

- The bundled dataset comes from `GB50009-2012` table `E.5`.
- Prefer `r100` values unless the user or downstream workflow explicitly needs another return period.
- Treat returned values as load context and surface any ambiguity before using them in safety-critical modeling.
