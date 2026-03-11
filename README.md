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
