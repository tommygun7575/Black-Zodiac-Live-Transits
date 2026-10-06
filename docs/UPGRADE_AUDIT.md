# Black Zodiac Live Transits — Upgrade Audit

**Date:** 2026-10-06 (PT)  
**Branch:** `upgrade/full-celestial-stack`  
**Repo:** tommygun7575/Black-Zodiac-Live-Transits  
**Scope:** Black Zodiac Oracle Android + ORACLE 13 celestial stack upgrade  
**Constraint:** Preserve JPL Horizons → Miriade → Swiss provider order; no fabricated coordinates.

## Executive summary

The live daily pipeline (`scripts/generate_transits.py` → `docs/feed_overlay_YYYY_MM_DD.json`) already resolves **41 moving bodies + 9 fixed stars + 3 Aether points** at **100% coverage** via Horizons-first fallback. Harmonic aspects and fixed-star conjunctions are present. Several Oracle layers required for the full celestial stack are **missing or only partial**, and daily vs 6-month feeds are **not field-parity**.

Legacy `scripts/generate_feed_overlay.py` still contains house cusps, Arabic parts, and invented Aether names (`Vulcan`, `Hades`, …) with `force_fallback=True` — **not** used by the current CI daily workflow. Production path is `generate_transits.py` / `fetch_ephemeris.py`.

## Config / data inventory

| Asset | Role | Notes |
|-------|------|-------|
| `config/celestial_catalog.json` | **Source of truth** for daily + 6mo | categories: core, dwarfs, majors, expanded, centaurs, TNOs, fixed_stars (9), aether (3). **No lunar nodes.** |
| `config/asteroids_master.json` | Thematic lists | **Invalid JSON** (`//` comments); unused by scripts |
| `config/live_config.json` | Natal + 4 stars + Chiron | Unused by modern generators; outdated vs catalog |
| `config/targets.json` | Natal file pointers | Overlay/natal targeting only |
| `data/fixed_star_catalog.json` / `fixed_stars.json` | Verified J2000 RA/Dec | **19** classical stars; catalog only enables **9** |
| `data/small_bodies_master.json` | Reference list | Not wired into generators |
| `schemas/daily_overlay.schema.json` | Schema | **Stale** vs current feed (requires `arabic_parts`/`natal_overlays` absent from modern feed) |
| `.github/workflows/daily_transit_snapshot.yml` | CI daily | validate compile → generate → key check → commit; **no pytest** |
| `.github/workflows/transits_6month.yml` | CI 6mo | generate → commit; **no validate/tests** |

## Provider architecture (PRESERVE)

1. **NASA JPL Horizons** (primary for mapped moving bodies)  
2. **IMCCE Miriade** (fallback)  
3. **Swiss Ephemeris** local (`ephe/`) (final fallback / nodes / Swiss-only)  
4. **fixed_star_catalog** (RA/Dec → ecliptic via `scripts/utils/coords.py`)  
5. **calculated** (Aether formulas only)

Latest daily proof (`docs/feed_overlay_2026_10_06.json`): `horizons:41`, `fixed_star_catalog:9`, `calculated:3`, coverage `1.0`.

## Layer classification

| Layer | Status | Evidence / gap |
|-------|--------|----------------|
| **Core planets** (Sun–Pluto) | **FULL** | Catalog `core_bodies` (10); resolved in daily feed |
| **Nodes** (Mean/True/South) | **MISSING** | Not in catalog; Swiss codes 10/11 available; South = True+180 formula unused |
| **Dwarf planets** | **FULL** | Ceres, Eris, Haumea, Makemake |
| **Major asteroids** | **FULL** | Pallas, Juno, Vesta, Hygiea |
| **Expanded asteroids** | **FULL** | Eros, Psyche, Sappho, Hekate, Nemesis, Karma, Destinn, Aura, Merlin |
| **Centaurs** | **FULL** | Chiron, Pholus, Nessus, Chariklo, Hylonome, Asbolus |
| **TNOs** | **FULL** | Orcus, Quaoar, Sedna, Gonggong, Ixion, Varuna, Huya, Salacia |
| **Rich fields** | **PARTIAL** | Have lon/lat/distance/velocity/source/timestamp/category. Missing: equatorial **declination**, **longitude_speed°/day**, retrograde/station flags. Horizons `velocity` is `vel_obs` (km/s), not λ̇ — cannot drive stations reliably |
| **Fixed stars** | **PARTIAL** | 9 enabled in catalog; 19 verified in `data/fixed_star_catalog.json` |
| **Houses / angles** | **UNSUPPORTED** (geocentric public feed) | No universal observer lat/lon. Legacy overlay computes Placidus for natal births. **Do not fabricate cusps.** Document as user-specific downstream |
| **Lunar geometry** | **MISSING** | No phase / elongation / illumination block in daily feed |
| **Stations** | **MISSING** | No station/retrograde layer; λ̇ not standardized across providers |
| **Aspects applying/exact/separating** | **PARTIAL** | `calculated_harmonics` has orb/separation; **no** applying/exact/separating status |
| **Declination aspects** | **MISSING** | No DEC on positions; no parallel/contraparallel |
| **Midpoints** | **PARTIAL** | Only Aetheric Sun–Moon midpoint formula; no general midpoint table |
| **Harmonics H3/5/7/9/12** | **PARTIAL** | Present: H2,3,4,5,6,8,9,12. **H7 (≈51.428°) missing** |
| **Geometric patterns** | **MISSING** | No grand trine / T-square / grand cross / yod / stellium detector |
| **Arabic parts** | **PARTIAL** | `calculate_aspects.arabic_parts` exists (Fortune/Spirit/Eros) but needs ASC+lat/lon; **not emitted** by modern daily generator. Schema still requires them |
| **Aether points** | **FULL** | Exactly 3 verified formulas in `fetch_ephemeris._compute_aether_points` / 6mo twin. Legacy overlay’s Vulcan/Hades list must stay unused |
| **Daily / 6mo parity** | **PARTIAL** | Same moving catalog count (41) + stars + aether, but field names differ (`longitude` vs `ecl_lon_deg`); 6mo lacks harmonics/patterns/stations/lunar geometry |
| **Schemas** | **PARTIAL** | Stale vs feed; CI uses ad-hoc key checks |
| **Tests** | **PARTIAL** | Strong `tests/test_generate_feed_6month.py`; no daily enrichment / aspect-status / aether / node tests |
| **CI** | **PARTIAL** | Daily: no pytest; 6mo: no validate→test gate before commit |

## Aether formulas (verified — DO NOT expand)

```
normalize(x) = ((x % 360) + 360) % 360
Aetheric_SunMoon_Midpoint     = normalize(Sun + Moon)
Aetheric_Jovian_Arc           = normalize(Jupiter - Saturn)
Aetheric_Elemental_Balance    = normalize((Moon + Venus + Mars) / 3)
```

## Houses policy (locked)

Geocentric public feeds remain location-agnostic. House cusps, ASC, MC are **user-specific** and must be computed downstream from natal/user lat/lon (Swiss `swe.houses`). Feed must document this — never invent cusps.

## Implementation priority (Phase 2)

1. Shared `scripts/utils/celestial_math.py` (normalize, ecl→eq, lunar geometry, midpoints, stations, aspect motion, patterns)  
2. Catalog: lunar nodes + expand fixed stars to verified 19  
3. Enrich positions: declination, longitude_speed (Swiss when mapped), retrograde/station  
4. Extend aspects: H7, applying/exact/separating, declination parallels, midpoints, patterns  
5. Wire into daily generator; enrich 6mo position fields for parity  
6. Schemas + tests + CI gate (validate→test→generate→schema→coverage→commit)  
7. Run generators + `docs/COVERAGE_REPORT.md`

## Acceptance targets (Phase 3)

Answer all 12 acceptance points; final flag **FULL CELESTIAL STACK COMPLETE: YES/NO** with proof paths and commit SHAs.
