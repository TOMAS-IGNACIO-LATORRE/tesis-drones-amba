#!/usr/bin/env python3
"""
Capa de restricciones de espacio aéreo para drones en el AMBA, construida a
partir de los aeródromos y helipuertos de OurAirports (dominio público) y de
las distancias que fija la RAAC Parte 100 (ANAC, 1ª edición abril 2025,
docs/regulacion/raac_parte_100.pdf, sección 100.x "Operaciones en espacio
aéreo controlado" y "helipuertos").

    python scripts/build_espacio_aereo.py

Reglas codificadas (RAAC 100):
  - Aeródromos: dentro de un radio de 3 NM de un aeródromo la altura máxima
    es 150 ft sobre la cota del umbral; fuera de ese radio, 200 ft en espacio
    aéreo controlado. Además no se puede operar dentro de las superficies de
    aproximación y despegue, que no se modelan acá (requieren la geometría de
    pista de cada aeródromo).
  - Helipuertos: prohibido dentro de 1 NM del punto de referencia (HRP);
    máximo 150 ft entre 1 y 2 NM.
  - Corredores VFR: prohibido a menos de 1/2 NM del límite lateral. No se
    modelan: hace falta la geometría de los corredores (AIP / EANA).
  - La categoría abierta excluye además las CTR de aeródromos controlados y
    no controlados; los polígonos CTR/TMA salen del AIP Argentina (EANA) u
    OpenAIP y NO están en esta capa. Es la carencia principal a cubrir.

Entrada:  data/raw/espacio_aereo/aerodromos_amba_ourairports.csv
Salida:   data/processed/espacio_aereo_amba.geojson   polígonos de restricción
          data/processed/aerodromos_amba.geojson       puntos con tipo y regla
          data/processed/espacio_aereo_amba_resumen.csv

Nota: la RAAC 100 usada es el texto de la primera edición (abril 2025). La
Resolución ANAC 550/2025 y las 311/312/313 de 2026 pueden haber ajustado
distancias: verificar contra el texto vigente antes de usar en la tesis.
"""

import os

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box

SRC = "data/raw/espacio_aereo/aerodromos_amba_ourairports.csv"
OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OUT = "data/processed"
NM = 1852.0                       # metros por milla náutica
CRS_METRICO = "EPSG:5347"         # POSGAR 2007 faja 5 (Buenos Aires)
BBOX_AMBA = (-59.30, -35.20, -57.90, -34.15)

# Aeródromos con servicio de tránsito aéreo (CTR) en el AMBA, según AIP
# Argentina. Se marcan para que la capa distinga "controlado" de "no
# controlado"; el polígono CTR real hay que agregarlo desde el AIP.
CONTROLADOS = {"SABE", "SAEZ", "SADP", "SADF", "SADO", "SADM", "SADJ"}


def asegurar_aerodromos():
    """Si no está el recorte del AMBA, baja airports.csv de OurAirports
    (dominio público, ~13 MB) y lo filtra a Argentina dentro del bbox."""
    if os.path.exists(SRC):
        return
    import requests
    os.makedirs(os.path.dirname(SRC), exist_ok=True)
    crudo = os.path.join(os.path.dirname(SRC), "ourairports_airports.csv")
    if not os.path.exists(crudo):
        print(f"Bajando {OURAIRPORTS} ...")
        r = requests.get(OURAIRPORTS, timeout=120)
        r.raise_for_status()
        with open(crudo, "wb") as f:
            f.write(r.content)
    a = pd.read_csv(crudo)
    lon0, lat0, lon1, lat1 = BBOX_AMBA
    a = a[(a.iso_country == "AR") & a.latitude_deg.between(lat0, lat1) & a.longitude_deg.between(lon0, lon1)]
    a.to_csv(SRC, index=False)
    print(f"Aeródromos de OurAirports en el bbox del AMBA: {len(a)} -> {SRC}")


def main():
    asegurar_aerodromos()
    a = pd.read_csv(SRC)
    a = a[~a["type"].isin(["closed", "balloonport"])].copy()
    a["ident"] = a["ident"].astype(str)
    a["icao"] = a["icao_code"].fillna(a["ident"].where(a["ident"].str.match(r"^SA[A-Z]{2}$")))
    a["controlado"] = a["icao"].isin(CONTROLADOS)
    a["clase"] = a["type"].map({"large_airport": "aeródromo", "medium_airport": "aeródromo",
                                "small_airport": "aeródromo", "heliport": "helipuerto",
                                "seaplane_base": "aeródromo"}).fillna("otro")
    pts = gpd.GeoDataFrame(a, geometry=[Point(x, y) for x, y in zip(a.longitude_deg, a.latitude_deg)],
                           crs="EPSG:4326")

    m = pts.to_crs(CRS_METRICO)
    zonas = []
    for _, r in m.iterrows():
        base = dict(ident=r.ident, nombre=r["name"], clase=r.clase, icao=r.icao,
                    controlado=bool(r.controlado), municipio=r.municipality)
        if r.clase == "aeródromo":
            zonas.append({**base, "regla": "RAAC100 aeródromo: radio 3 NM, altura máx 150 ft",
                          "radio_nm": 3, "altura_max_ft": 150, "prohibido": False,
                          "geometry": r.geometry.buffer(3 * NM)})
        elif r.clase == "helipuerto":
            zonas.append({**base, "regla": "RAAC100 helipuerto: prohibido dentro de 1 NM del HRP",
                          "radio_nm": 1, "altura_max_ft": 0, "prohibido": True,
                          "geometry": r.geometry.buffer(1 * NM)})
            zonas.append({**base, "regla": "RAAC100 helipuerto: altura máx 150 ft entre 1 y 2 NM del HRP",
                          "radio_nm": 2, "altura_max_ft": 150, "prohibido": False,
                          "geometry": r.geometry.buffer(2 * NM).difference(r.geometry.buffer(1 * NM))})
    z = gpd.GeoDataFrame(zonas, geometry="geometry", crs=CRS_METRICO)
    z["area_km2"] = (z.area / 1e6).round(3)

    os.makedirs(OUT, exist_ok=True)
    z.to_crs("EPSG:4326").to_file(os.path.join(OUT, "espacio_aereo_amba.geojson"), driver="GeoJSON")
    cols = ["ident", "icao", "name", "clase", "type", "controlado", "municipality",
            "latitude_deg", "longitude_deg", "elevation_ft", "geometry"]
    pts[cols].to_file(os.path.join(OUT, "aerodromos_amba.geojson"), driver="GeoJSON")

    # Resumen: cuánto del bbox del AMBA queda bajo cada tipo de restricción
    bbox = gpd.GeoSeries([box(*BBOX_AMBA)], crs="EPSG:4326").to_crs(CRS_METRICO).iloc[0]
    res = []
    for etiqueta, sel in [("prohibido (helipuerto < 1 NM)", z[z.prohibido]),
                          ("altura máx 150 ft (aeródromo < 3 NM)", z[(z.clase == "aeródromo")]),
                          ("altura máx 150 ft (helipuerto 1-2 NM)", z[(z.clase == "helipuerto") & (~z.prohibido)]),
                          ("cualquier restricción", z)]:
        u = sel.geometry.union_all().intersection(bbox)
        res.append(dict(restriccion=etiqueta, zonas=len(sel), area_km2=round(u.area / 1e6, 1),
                        pct_bbox_amba=round(100 * u.area / bbox.area, 1)))
    res = pd.DataFrame(res)
    res.to_csv(os.path.join(OUT, "espacio_aereo_amba_resumen.csv"), index=False)

    print(f"Aeródromos/helipuertos activos en el bbox: {len(pts)} "
          f"({(pts.clase == 'aeródromo').sum()} aeródromos, {(pts.clase == 'helipuerto').sum()} helipuertos, "
          f"{pts.controlado.sum()} con CTR)")
    print(f"Zonas generadas: {len(z)} -> {OUT}/espacio_aereo_amba.geojson")
    print(res.to_string(index=False))
    print("\nPendiente (no modelado): polígonos CTR/TMA y corredores VFR del AIP Argentina (EANA).")


if __name__ == "__main__":
    main()
