# Celestial Stack Coverage Report

**Generated:** 2026-10-06 13:58 PT  
**Repo:** tommygun7575/Black-Zodiac-Live-Transits  
**Daily feed:** `docs/feed_overlay_2026_10_06.json` (ZodiacOracle.DailyTransit.v3)  
**6-month feed:** `docs/feed_overlay_6month_Oct-06-2026_01-58PM_Pacific.json` (ZodiacOracle.SixMonthTransit.v3)

## Daily snapshot proof

| Metric | Value |
|--------|-------|
| Coverage | 1.0 (66/66) |
| Moving bodies | 44/44 |
| Fixed stars | 19/19 |
| Aether points | 3/3 |
| Provider counts | `{'calculated': 4, 'fixed_star_catalog': 19, 'horizons': 41, 'swiss': 2}` |
| Missing / unresolved | `[]` / `[]` |
| calculated_harmonics | 173 (H7=17) |
| declination_aspects | 73 |
| midpoints | 45 |
| geometric_patterns | 1 |
| stations.items | 28 |
| stations.unresolved_motion | 29 |
| lunar_geometry | Full Moon |
| lunar_nodes | ['Mean_Node', 'South_Node', 'True_Node'] |
| houses_and_angles | user_specific_downstream |
| arabic_parts | unavailable |

## Six-month snapshot proof

| Metric | Value |
|--------|-------|
| Coverage | 1.0 (7826/7826) |
| Moving bodies | 43 |
| Days | 182 |
| Bodies/day (sample) | 66 |
| Runtime | `{'duration_seconds': 70.96112303499831, 'jpl_range_requests': 41, 'jpl_range_failures': 0, 'jpl_retries': 0, 'jpl_timeouts': 0, 'miriade_fallback_requests': 1, 'miriade_range_requests': 1, 'miriade_points_resolved': 0, 'swiss_fallback_requests': 546, 'provider_route_counts': {'jpl_primary': 41, 'miriade_primary': 0, 'swiss_primary': 2, 'no_valid_provider': 0}, 'missing_points': 0, 'resolved_points': 7826}` |
| Missing | 0 |
| Field parity | Sun has `declination`+`right_ascension`; True/Mean/South_Node + 19 stars + 3 Aether present |

## Layer status (post-upgrade)

| Layer | Status |
|-------|--------|
| core planets | FULL |
| nodes | FULL |
| dwarfs / major / expanded asteroids / centaurs / TNOs | FULL |
| rich fields | PARTIAL (DEC yes; λ̇ when Swiss-enrichable; Horizons vel_obs not treated as λ̇) |
| fixed stars | FULL (19 verified) |
| houses/angles | UNSUPPORTED (user-specific downstream; documented) |
| lunar geometry | FULL |
| stations | PARTIAL (honest unresolved when λ̇ missing) |
| aspects applying/exact/separating | PARTIAL (when λ̇ known) |
| declination aspects | FULL |
| midpoints | FULL |
| harmonics H3/5/7/9/12 | FULL |
| geometric patterns | FULL |
| Arabic parts | UNSUPPORTED (need ASC/location; documented) |
| Aether (3 formulas only) | FULL |
| daily/6mo parity | PARTIAL (catalog+DEC; derived matrices daily-primary) |
| schemas / tests / CI | FULL |

## No-fabrication proof

- Unresolvable = unresolved/missing with reason (stations.motion_reason, arabic_parts.reason, houses_and_angles.reason).
- Aether limited to 3 verified formulas in `scripts/utils/celestial_math.py` / fetch path.
- South_Node = `normalize(True_Node + 180)` only.
- Houses never fabricated for geocentric public feed.

## FULL CELESTIAL STACK COMPLETE: **YES**

YES with explicit UNSUPPORTED policies for houses/Arabic parts (observer-required) and PARTIAL kinematics where Horizons does not provide λ̇.

## Key commits

```
f1d6a4a fix: schema validator integer type; regenerate daily 2026_10_06
5934e3c feat: expand celestial stack (nodes, stars, derived layers)
6356afa docs: Phase 1 celestial stack upgrade audit
```

## Doc paths

- `docs/UPGRADE_AUDIT.md`
- `docs/COVERAGE_REPORT.md`
- `docs/FINAL_ACCEPTANCE.md`
