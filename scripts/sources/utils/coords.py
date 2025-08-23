import math
OBLIQUITY_J2000_DEG=23.43929111

def ra_dec_to_ecl(ra_deg:float,dec_deg:float,when_iso:str):
    ra,dec,eps=map(math.radians,[ra_deg,dec_deg,OBLIQUITY_J2000_DEG])
    sinb=math.sin(dec)*math.cos(eps)-math.cos(dec)*math.sin(eps)*math.sin(ra)
    b=math.asin(sinb)
    y=math.sin(ra)*math.cos(eps)+math.tan(dec)*math.sin(eps)
    x=math.cos(ra)
    l=math.atan2(y,x)
    return (math.degrees(l)%360.0,math.degrees(b))
