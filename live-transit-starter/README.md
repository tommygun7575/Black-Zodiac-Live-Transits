# Live Transit Feed (JPL Horizons → GitHub Pages)

This repo fetches **geocentric ecliptic positions** (EclLon/EclLat) for a set of Solar System bodies from **JPL Horizons** using **astroquery**, then writes `docs/feed_now.json`. A GitHub Actions workflow runs on a schedule and commits updates, so the file is served on GitHub Pages at:

```
https://<your-username>.github.io/<your-repo>/feed_now.json
```

## What’s included
- `scripts/fetch_transits.py` — Python script that queries JPL Horizons (via astroquery) for “now” (UTC) and outputs JSON.
- `.github/workflows/transit.yml` — CI job to run every 30 minutes and on manual dispatch. Commits changes to `docs/feed_now.json`.
- `config/targets.json` — List of objects the script will query. Edit this to add/remove targets.
- `docs/` — Where the JSON is written. Configure **GitHub Pages** to serve from the `main` branch `/docs` folder.

## Quick start
1. Create a **new GitHub repo** (public or private).
2. Upload all files from this starter into your repo root (keep the same structure).
3. In **Settings → Pages**, set *Build and deployment* to **Deploy from a branch**, Branch: `main`, Folder: `/docs`.
4. In **Settings → Actions → General**, ensure **Workflow permissions** includes “Read and write permissions” for the GITHUB_TOKEN.
5. The workflow runs every 30 minutes (UTC) and on **Run workflow** (manual). First run writes `docs/feed_now.json`.
6. Your live JSON will be at: `https://<your-username>.github.io/<your-repo>/feed_now.json`.

## Notes
- The script uses **geocentric** (Earth center) by default. You can switch to a topocentric site by passing coordinates to the Horizons `location` if you prefer.
- Columns used from Horizons: `EclLon`, `EclLat`, `RA`, `DEC`, `delta`, `r`, plus `targetname` and timestamps.
- Extend `config/targets.json` for additional asteroids/TNOs. Numeric designations reduce ambiguity.
