#!/usr/bin/env python3
import json,os,sys
from datetime import datetime,timezone
from typing import Dict,Any,List
from scripts.sources import horizons_client,miriade_client,mpc_client,swiss_client

OBJECTS=["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Uranus",
         "Neptune","Pluto","Chiron","Ceres","Pallas","Juno","Vesta","Astraea",
         "Psyche","Amor","Eros","Sappho","Karma","Bacchus","Euphrosyne",
         "Pholus","Chariklo","Haumea","Makemake","Eris","Varuna","Ixion",
         "Typhon","Salacia"]

FIXED_STARS={"Regulus":150.0,"Spica":204.0,"Sirius":104.0,"Aldebaran":69.0,
             "Antares":249.0,"Fomalhaut":345.0}

SOURCE_ORDER=(("jpl",horizons_client.get_ecliptic_lonlat),
              ("miriade",miriade_client.get_ecliptic_lonlat),
              ("mpc",mpc_client.get_ecliptic_lonlat),
              ("swiss",swiss_client.get_ecliptic_lonlat))

def iso_now()->str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

def load_existing(path:str)->Dict[str,Any]:
    if os.path.exists(path):
        try: return json.load(open(path))
        except Exception: return {}
    return {}

def compute_positions(when_iso:str)->Dict[str,Dict[str,Any]]:
    out={}
    for name in OBJECTS+list(FIXED_STARS.keys()):
        if name in FIXED_STARS:
            out[name]={"ecl_lon_deg":FIXED_STARS[name],"ecl_lat_deg":0.0,"source":"fixed"}; continue
        got=None; used=None
        for label,func in SOURCE_ORDER:
            pos=func(name,when_iso)
            if pos: got,used=pos,label; break
        out[name]={"ecl_lon_deg":None if not got else float(got[0]),
                   "ecl_lat_deg":0.0 if not got else float(got[1]),
                   "source":"missing" if not used else used}
    return out

def merge_into(existing:Dict[str,Any],positions:Dict[str,Dict[str,Any]],when_iso:str)->Dict[str,Any]:
    meta=existing.get("meta",{})
    meta.update({"generated_at_utc":when_iso,"source_order":[s for s,_ in SOURCE_ORDER]})
    charts=existing.get("charts")
    if charts and isinstance(charts,dict):
        for who,chart in charts.items():
            chart.setdefault("objects",{})
            chart["objects"].update(positions)
        out={"meta":meta,"charts":charts}
    else:
        out={"meta":meta,"objects":positions}
    return out

def main(argv:List[str]):
    out_path=os.environ.get("OVERLAY_OUT",os.path.join("docs","feed_overlay.json"))
    when_iso=os.environ.get("OVERLAY_TIME_UTC",iso_now())
    os.makedirs(os.path.dirname(out_path),exist_ok=True)
    existing=load_existing(out_path)
    positions=compute_positions(when_iso)
    merged=merge_into(existing,positions,when_iso)
    json.dump(merged,open(out_path,'w'),indent=2,ensure_ascii=False)
    print(f"wrote {out_path}")

if __name__=="__main__": main(sys.argv[1:])
