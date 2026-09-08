#!/usr/bin/env python3
"""
Extracción de urbanizaciones cerradas (categoría 55191) desde la API de
Wikimapia, replicando la metodología de De Grande (2022) para obtener un
corte actualizado.

Uso:
    export WIKIMAPIA_KEY="tu-clave"
    python extraer_wikimapia.py --region amba
    python extraer_wikimapia.py --region argentina --salida ./out

Clave gratuita: https://wikimapia.org/api/?action=my_keys
Límite: 100 requests cada 5 minutos por clave.

Dependencias: requests, shapely, pandas
    pip install requests shapely pandas
"""

import argparse
import csv
import json
import math
import os
import sys
import time
from collections import deque

import requests

API_URL = "http://api.wikimapia.org/"
CATEGORIA_BARRIOS_CERRADOS = 55191

# Límite oficial: 100 requests / 5 min. Dejamos margen: 90 / 300 s.
MAX_REQUESTS = 90
VENTANA_SEG = 300

# La API devuelve como mucho 100 objetos por página. No documenta un tope
# de páginas, pero en la práctica conviene subdividir el tile antes de
# paginar demasiado: menos requests y menos riesgo de truncamiento.
MAX_POR_PAGINA = 100
UMBRAL_SUBDIVISION = 500      # si un tile trae más que esto, se parte en 4
PROFUNDIDAD_MAX = 6           # corta la recursión

REGIONES = {
    # lon_min, lat_min, lon_max, lat_max  (WGS84)
    "amba": (-59.30, -35.20, -57.90, -34.15),
    "corredor_norte": (-59.15, -34.55, -58.45, -34.20),
    "delta_tigre": (-58.75, -34.42, -58.40, -34.05),
    "argentina": (-73.60, -55.10, -53.60, -21.75),
}


class Limitador:
    """Ventana deslizante: nunca más de MAX_REQUESTS en VENTANA_SEG."""

    def __init__(self, max_requests=MAX_REQUESTS, ventana=VENTANA_SEG):
        self.max_requests = max_requests
        self.ventana = ventana
        self.marcas = deque()

    def esperar(self):
        ahora = time.time()
        while self.marcas and ahora - self.marcas[0] > self.ventana:
            self.marcas.popleft()
        if len(self.marcas) >= self.max_requests:
            dormir = self.ventana - (ahora - self.marcas[0]) + 1
            print(f"    [rate limit] esperando {dormir:.0f} s...", flush=True)
            time.sleep(dormir)
            return self.esperar()
        self.marcas.append(time.time())


def consultar(clave, bbox, pagina, limitador, reintentos=4):
    """Una llamada a place.getbyarea. Devuelve el JSON parseado."""
    lon_min, lat_min, lon_max, lat_max = bbox
    params = {
        "key": clave,
        "function": "place.getbyarea",
        "coordsby": "bbox",
        "bbox": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "category": CATEGORIA_BARRIOS_CERRADOS,
        "count": MAX_POR_PAGINA,
        "page": pagina,
        "format": "json",
        "language": "es",
        "disable": "comments,photos,translate",
    }
    espera = 5
    for intento in range(reintentos):
        limitador.esperar()
        try:
            r = requests.get(API_URL, params=params, timeout=45)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            print(f"    error de red ({e}); reintento en {espera} s", flush=True)
            time.sleep(espera)
            espera *= 2
            continue

        # La API devuelve errores con HTTP 200
        if isinstance(data, dict) and "debug" in data:
            msg = str(data["debug"])
            if "limit" in msg.lower():
                print(f"    la API reporta límite alcanzado; espero 60 s", flush=True)
                time.sleep(60)
                continue
            raise RuntimeError(f"Error de la API: {msg}")
        return data

    raise RuntimeError(f"No se pudo consultar el bbox {bbox} tras {reintentos} intentos")


def poligono_a_wkt(poligono):
    """Convierte la lista [{'x': lon, 'y': lat}, ...] a WKT POLYGON."""
    if not poligono or len(poligono) < 3:
        return None
    pts = [(float(v["x"]), float(v["y"])) for v in poligono]
    if pts[0] != pts[-1]:
        pts.append(pts[0])          # WKT exige anillo cerrado
    coords = ", ".join(f"{x} {y}" for x, y in pts)
    return f"POLYGON (({coords}))"


def recolectar(clave, bbox, limitador, encontrados, profundidad=0):
    """Recorre un bbox, subdividiendo si trae demasiados objetos."""
    sangria = "  " * profundidad
    lon_min, lat_min, lon_max, lat_max = bbox

    primera = consultar(clave, bbox, 1, limitador)
    total = int(primera.get("found", 0))
    print(f"{sangria}bbox {lon_min:.3f},{lat_min:.3f},{lon_max:.3f},{lat_max:.3f} "
          f"-> {total} objetos", flush=True)

    if total == 0:
        return

    if total > UMBRAL_SUBDIVISION and profundidad < PROFUNDIDAD_MAX:
        lon_mid = (lon_min + lon_max) / 2
        lat_mid = (lat_min + lat_max) / 2
        cuadrantes = [
            (lon_min, lat_min, lon_mid, lat_mid),
            (lon_mid, lat_min, lon_max, lat_mid),
            (lon_min, lat_mid, lon_mid, lat_max),
            (lon_mid, lat_mid, lon_max, lat_max),
        ]
        for q in cuadrantes:
            recolectar(clave, q, limitador, encontrados, profundidad + 1)
        return

    paginas = math.ceil(total / MAX_POR_PAGINA)
    for pagina in range(1, paginas + 1):
        data = primera if pagina == 1 else consultar(clave, bbox, pagina, limitador)
        for obj in data.get("folder", []):
            oid = int(obj["id"])
            if oid in encontrados:
                continue
            loc = obj.get("location", {}) or {}
            encontrados[oid] = {
                "id": oid,
                "nombre": (obj.get("name") or "").strip(),
                "url": obj.get("url", f"http://wikimapia.org/{oid}/"),
                "wkt": poligono_a_wkt(obj.get("polygon")),
                "lat": loc.get("lat"),
                "lon": loc.get("lon"),
            }


def superficie_km2(wkt_str):
    """Área en km2 proyectando a una cónica de igual área local."""
    try:
        from shapely import wkt as shp_wkt
        from shapely.ops import transform
        from pyproj import Transformer
    except ImportError:
        return None
    geom = shp_wkt.loads(wkt_str)
    lon, lat = geom.centroid.x, geom.centroid.y
    proj = (f"+proj=aea +lat_1={lat - 1} +lat_2={lat + 1} "
            f"+lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m")
    tr = Transformer.from_crs("EPSG:4326", proj, always_xy=True)
    return transform(tr.transform, geom).area / 1e6


def escribir_csv(registros, ruta):
    campos = ["id", "nombre", "url", "wkt", "lat", "lon", "superficie_km2"]
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for r in registros:
            w.writerow({c: r.get(c) for c in campos})


def escribir_geojson(registros, ruta):
    try:
        from shapely import wkt as shp_wkt
    except ImportError:
        print("  (shapely no instalado: se omite el GeoJSON)")
        return
    feats = []
    for r in registros:
        if not r.get("wkt"):
            continue
        g = shp_wkt.loads(r["wkt"])
        props = {k: v for k, v in r.items() if k != "wkt"}
        feats.append({"type": "Feature",
                      "geometry": g.__geo_interface__,
                      "properties": props})
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection",
                   "crs": {"type": "name",
                           "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
                   "features": feats}, f, ensure_ascii=False)


def comparar_con_2022(registros, ruta_csv_2022):
    """Compara el corte nuevo contra el dataset de Poblaciones 2022."""
    try:
        import pandas as pd
    except ImportError:
        print("  (pandas no instalado: se omite la comparación)")
        return
    viejo = pd.read_csv(ruta_csv_2022)
    col_id = "id" if "id" in viejo.columns else viejo.columns[0]
    ids_2022 = set(viejo[col_id].astype(int))
    ids_hoy = {r["id"] for r in registros}

    nuevos = ids_hoy - ids_2022
    desaparecidos = ids_2022 - ids_hoy
    print()
    print("COMPARACIÓN CONTRA EL CORTE DE ABRIL 2022")
    print(f"  registros 2022 (dataset completo): {len(ids_2022)}")
    print(f"  registros en esta extracción:      {len(ids_hoy)}")
    print(f"  ids nuevos:                        {len(nuevos)}")
    print(f"  ids del 2022 no hallados:          {len(desaparecidos)}")
    print()
    print("  Ojo: el dataset 2022 cubre todo el país. Si extrajiste solo el")
    print("  AMBA, 'no hallados' incluye todo lo que está fuera del bbox y no")
    print("  significa que haya desaparecido. Filtrá el 2022 por provincia")
    print("  antes de leer ese número.")
    print()
    print("  Ojo 2: parte de los ids nuevos son urbanizaciones que ya existían")
    print("  pero que nadie había cargado en Wikimapia en 2022. El delta mide")
    print("  crecimiento del registro colaborativo, no obra nueva. Declaralo.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="amba", choices=sorted(REGIONES),
                    help="región predefinida a extraer")
    ap.add_argument("--bbox", help="bbox propio: lon_min,lat_min,lon_max,lat_max")
    ap.add_argument("--salida", default=".", help="directorio de salida")
    ap.add_argument("--clave", default=os.environ.get("WIKIMAPIA_KEY"),
                    help="clave de API (o variable WIKIMAPIA_KEY)")
    ap.add_argument("--comparar", help="ruta al CSV de Poblaciones 2022")
    args = ap.parse_args()

    if not args.clave:
        sys.exit("Falta la clave. Pedila en https://wikimapia.org/api/?action=my_keys\n"
                 "Después: export WIKIMAPIA_KEY='tu-clave'")

    if args.bbox:
        bbox = tuple(float(v) for v in args.bbox.split(","))
        etiqueta = "custom"
    else:
        bbox = REGIONES[args.region]
        etiqueta = args.region

    os.makedirs(args.salida, exist_ok=True)

    print(f"Extrayendo categoría {CATEGORIA_BARRIOS_CERRADOS} sobre '{etiqueta}'")
    print(f"bbox: {bbox}")
    print()

    encontrados = {}
    inicio = time.time()
    recolectar(args.clave, bbox, Limitador(), encontrados)

    registros = sorted(encontrados.values(), key=lambda r: r["id"])
    for r in registros:
        r["superficie_km2"] = (round(superficie_km2(r["wkt"]), 6)
                               if r.get("wkt") else None)

    sin_poligono = sum(1 for r in registros if not r.get("wkt"))
    minutos = (time.time() - inicio) / 60

    base = os.path.join(args.salida, f"urbanizaciones_{etiqueta}_"
                                     f"{time.strftime('%Y%m%d')}")
    escribir_csv(registros, base + ".csv")
    escribir_geojson(registros, base + ".geojson")

    print()
    print(f"Listo en {minutos:.1f} min")
    print(f"  objetos únicos: {len(registros)}")
    print(f"  sin polígono:   {sin_poligono}")
    print(f"  CSV:      {base}.csv")
    print(f"  GeoJSON:  {base}.geojson")

    if args.comparar:
        comparar_con_2022(registros, args.comparar)


if __name__ == "__main__":
    main()
