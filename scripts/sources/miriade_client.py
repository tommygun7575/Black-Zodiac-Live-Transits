import json, requests
from typing import Tuple, Optional

MIRIADE_BASE = "https://ssp.imcce.fr/webservices/miriade/api/ephemcc.php"
PREFIX_MAP = {"Sun":"p:","Mercury":"p:","Venus":"p:","Earth":"p:","Moon":"s:",
              "Mars":"p:","Jupiter":"p:","Saturn":"p:","Uranus":"p:",
              "Neptune":"p:","Pluto":"dp:","Chiron":"a:","Ceres":"dp:",
              "Pallas":"a:","Juno":"a:","Vesta":"a:"}

def _qualify(name: str) -> str: return f"{PREFIX_MAP.get(name,'a:')}{name}"

def get_ecliptic_lonlat(name: str, when_iso: str) -> Optional[Tuple[float, float]]:
    params = {"-name": _qualify(name), "-ep": when_iso, "-observer": "500",
              "-theory": "DE431", "-teph": "1", "-tcoor": "1", "-rplane": "2",
              "-nbd": "1", "-mime": "json"}
    try:
        r = requests.get(MIRIADE_BASE, params=params, timeout=30)
        data = r.json().get("result",{})
        if isinstance(data,str): data=json.loads(data)
        rows=data.get("data",[])
        if not rows: return None
        row={k.lower():v for k,v in rows[0].items()}
        elon=row.get("elon") or row.get("ecllon"); elat=row.get("elat") or row.get("ecllat")
        if elon is None or elat is None:
            ra=row.get("ra"); dec=row.get("dec")
            if ra and dec:
                from scripts.utils.coords import ra_dec_to_ecl
                return ra_dec_to_ecl(float(ra),float(dec),when_iso)
            return None
        return (float(elon)%360.0,float(elat))
    except Exception: return None
