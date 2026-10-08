# Black Zodiac Live Transits

Deterministic daily transit pipeline with tiered ephemeris sourcing:
1. NASA JPL Horizons
2. IMCCE Miriade fallback
3. Swiss Ephemeris local fallback

## Pipeline layout

```text
repo/
  scripts/
    fetch_ephemeris.py
    generate_transits.py
    calculate_aspects.py
    overlay_engine.py
  config/
    celestial_catalog.json
    natal_profiles.json
  output/
    daily_overlays/
  .github/workflows/
    generate_daily_transits.yml
```

## Run locally

```bash
pip install -r requirements.txt
PYTHONPATH=$(pwd) python scripts/generate_transits.py --date 2026-03-11
latest=$(ls -t output/daily_overlays/daily_overlay_*.json | head -n 1)
PYTHONPATH=$(pwd) python scripts/validate_output_schema.py "$latest"
```

## Motion, station and derived-layer rules (2026-10-08)

- **Daily (`ZodiacOracle.DailyTransit.v3`)** — current activation. Motion uses `longitude_speed` only (`velocity` is provider-native and never zodiac speed). Fixed stars: `station=false`, `motion_status="fixed"`. Aether points, Sun, Moon and lunar nodes never produce station events. Null `longitude_speed` stays `motion_status="unresolved"` with `motion_fallback_available=["weekly_6h_difference","six_month_series"]`. The daily feed is not the authoritative station source. `calculated_harmonics` rows are `scope="transit_to_transit_sky_geometry"`; the embedded natal/houses/Arabic Parts blocks are `data_role=reference_test_data`. CI: `scripts/validate_daily_motion.py` writes `docs/derived/daily_motion_validation_YYYY_MM_DD.json`.
- **Six-month (`ZodiacOracle.SixMonthTransit.v3`)** — raw feed untouched. `scripts/sixmonth_derived.py` writes `docs/derived/sixmonth_derived_<stamp>.json`: sample instants = `meta.range_utc[0] + i days` (actual time of day, not midnight), speeds `wrap180(L[i+1]-L[i-1])/2` (one-sided at edges, `speed_source="six_month_central_difference"`), and authoritative true stations (physical bodies only, quadratic-vertex refinement, Swiss cross-check). `scripts/transit_to_natal.py` is a generic transit-to-natal engine (any natal chart). The reference report against the daily-feed embedded natal is test data only: `docs/derived/sixmonth_transit_to_natal_reference_<stamp>.json`. Orbs and rules: `config/transit_to_natal_rules.json` (copied from the Luminous Gate `aspects_orbs`). Workflow `sixmonth_derived.yml` derives the layer for an existing raw feed without regenerating it.
