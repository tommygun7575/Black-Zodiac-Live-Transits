import json
from pathlib import Path

def load_json(path):
    with open(path) as f:
        return json.load(f)

def build_overlay(natal_chart, transits):
    """
    Simple overlay builder: line up natal planets/points with transit positions.
    Expand with aspects, Arabic parts, harmonics, etc. later.
    """
    overlay = {
        "birth": natal_chart.get("birth", {}),
        "natal_planets": natal_chart.get("planets", {}),
        "transits_today": transits.get("planets", {}),
        "matches": {}
    }

    # Example: line up each natal planet with today’s degree
    for body, nat in natal_chart.get("planets", {}).items():
        trans = transits.get("planets", {}).get(body, None)
        if trans:
            overlay["matches"][body] = {
                "natal_degree": nat.get("degree"),
                "transit_degree": trans.get("degree"),
                "sign": trans.get("sign")
            }

    return overlay

def main():
    # Load natal bundle
    natal_path = Path("config/natal/3_combined_kitchen_sink.json")
    natal_bundle = load_json(natal_path)

    # Load today’s feed
    transit_path = Path("docs/feed_now.json")
    transits = load_json(transit_path)

    overlays = {}

    for person, natal_chart in natal_bundle.items():
        if person.startswith("_meta"):
            continue
        overlays[person] = build_overlay(natal_chart, transits)

    outpath = Path("docs/feed_overlay.json")
    with outpath.open("w") as f:
        json.dump(overlays, f, indent=2)

if __name__ == "__main__":
    main()
