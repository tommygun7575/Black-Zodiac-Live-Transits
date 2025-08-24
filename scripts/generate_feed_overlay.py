# scripts/generate_feed_overlay.py

def resolve_body(name, sources, force_fallback=False):
    got, used = None, None
    for label, func in sources:
        try:
            pos = func(name, when_iso)
        except Exception:
            pos = None
        if pos:
            got, used = pos, label
            break
    if not got and force_fallback:
        got, used = (0.0, 0.0), "calculated-fallback"
    return {"ecl_lon_deg": None if not got else float(got[0]),
            "ecl_lat_deg": None if not got else float(got[1]),
            "used_source": "missing" if not used else used}

def compute_positions(when_iso, lat, lon):
    out = {}
    MAJORS = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto", "Chiron"]
    ASTEROIDS = ["Ceres", "Pallas", "Juno", "Vesta", "Psyche", "Amor", "Eros", "Astraea", "Sappho", "Karma", "Bacchus", "Hygiea", "Nessus"]
    TNOs = ["Eris", "Sedna", "Haumea", "Makemake", "Varuna", "Ixion", "Typhon", "Salacia", "2002 AW197", "2003 VS2", "Orcus", "Quaoar"]
    AETHERS = ["Vulcan", "Persephone", "Hades", "Proserpina", "Isis"]

    # Majors (Horizons first, fallback to Swiss)
    for name in MAJORS:
        out[name] = resolve_body(name, [("jpl", horizons_client.get_ecliptic_lonlat),
                                        ("swiss", swiss_client.get_ecliptic_lonlat)], force_fallback=True)

    # Asteroids (Horizons first, fallback to Swiss)
    for name in ASTEROIDS:
        out[name] = resolve_body(name, [("jpl", horizons_client.get_ecliptic_lonlat),
                                        ("swiss", swiss_client.get_ecliptic_lonlat)], force_fallback=True)

    # TNOs (Horizons first, fallback to Swiss)
    for name in TNOs:
        out[name] = resolve_body(name, [("jpl", horizons_client.get_ecliptic_lonlat),
                                        ("swiss", swiss_client.get_ecliptic_lonlat)])

    # Aethers
    for name in AETHERS:
        out[name] = resolve_body(name, [("swiss", swiss_client.get_ecliptic_lonlat)])

    # Fixed stars
    stars = load_json(os.path.join(DATA, "fixed_stars.json"))["stars"]
    for s in stars:
        lam, bet = ra_dec_to_ecl(s["ra_deg"], s["dec_deg"], when_iso)
        out[s["id"]] = {"ecl_lon_deg": lam, "ecl_lat_deg": bet, "used_source": "fixed"}

    out.update(compute_house_cusps(lat, lon, when_iso))
    if "ASC" in out and "Sun" in out and "Moon" in out:
        asc, sun, moon = out["ASC"]["ecl_lon_deg"], out["Sun"]["ecl_lon_deg"], out["Moon"]["ecl_lon_deg"]
        if None not in (asc, sun, moon):
            out.update(compute_arabic_parts(asc, sun, moon))
    out.update(compute_harmonics(out))
    return out
