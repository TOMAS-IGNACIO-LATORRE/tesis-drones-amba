#!/usr/bin/env python3
"""
Extracción de urbanizaciones cerradas (categoría 55191) desde la API de
Wikimapia, replicando la metodología de De Grande (2022) para obtener un
corte actualizado.

Recorre la región por tiles XYZ (function=box con x,y,z) porque es la única
forma de consulta por área que hoy responde de manera consistente: cada
objeto cae en un único tile, y los cuatro hijos de un tile suman exactamente
el padre. Un tile con demasiados objetos se parte en sus hijos.

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

# Límite oficial: 100 requests / 5 min. En la práctica superarlo bloquea la
# clave por bastante más que 5 minutos (medido en 2026-09: más de 10), así
# que conviene ir bien por debajo: 50 / 300 s.
MAX_REQUESTS = 50
VENTANA_SEG = 300

# Directorio donde se guarda cada respuesta de la API (una por tile y
# página). Lo fija main() a partir de --cache. Permite reanudar una corrida
# interrumpida sin volver a gastar cuota.
CACHE_DIR = None

# La API devuelve como mucho 100 objetos por página. No documenta un tope
# de páginas ni de 'found', así que conviene partir el tile en sus 4 hijos
# antes de paginar mucho: menos requests y menos riesgo de truncamiento.
MAX_POR_PAGINA = 100
UMBRAL_SUBDIVISION = 300      # si un tile trae más que esto, se parte en 4
PROFUNDIDAD_MAX = 6           # niveles de zoom por debajo del inicial

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


def consultar(clave, x, y, z, pagina, limitador, reintentos=4):
    """Una llamada a la API (function=box por tile). Devuelve el JSON parseado."""
    params = {
        "key": clave,
        # place.getbyarea devuelve [] para cualquier consulta (verificado
        # 2026-09). La funcion legacy "box" responde con la misma estructura
        # (folder, found, page) y respeta el filtro de categoria, pero con
        # bbox elige un solo tile segun el centro de la caja y pierde objetos.
        # Por tile x,y,z es exacto: cada objeto cae en un unico tile y los
        # cuatro hijos de un tile suman exactamente el padre.
        "function": "box",
        "x": x,
        "y": y,
        "z": z,
        "category": CATEGORIA_BARRIOS_CERRADOS,
        "count": MAX_POR_PAGINA,
        "page": pagina,
        "format": "json",
        "language": "es",
        "disable": "comments,photos,translate",
    }
    ruta_cache = None
    if CACHE_DIR:
        ruta_cache = os.path.join(CACHE_DIR, f"z{z}_x{x}_y{y}_p{pagina}.json")
        if os.path.exists(ruta_cache):
            with open(ruta_cache, encoding="utf-8") as f:
                return json.load(f)

    espera = 5
    errores_red = 0
    bloqueos = 0
    while True:
        limitador.esperar()
        try:
            r = requests.get(API_URL, params=params, timeout=45)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            errores_red += 1
            if errores_red >= reintentos:
                raise RuntimeError(f"No se pudo consultar el tile {x},{y},z{z} "
                                   f"tras {reintentos} errores de red") from e
            print(f"    error de red ({e}); reintento en {espera} s", flush=True)
            time.sleep(espera)
            espera *= 2
            continue

        # La API devuelve errores con HTTP 200
        if isinstance(data, dict) and "debug" in data:
            msg = str(data["debug"])
            if "limit" in msg.lower():
                # Superar la cuota bloquea la clave por bastante más que la
                # ventana de 5 min, y cada request rechazado parece extender
                # el bloqueo. Esperamos con backoff (5, 10, 20... minutos,
                # tope 1 hora) y sin límite de intentos: no es un error, es
                # cuota. Con --cache, matar y relanzar no pierde lo hecho.
                bloqueos += 1
                dormir = min(VENTANA_SEG * 2 ** (bloqueos - 1), 3600) + 10
                print(f"    la API reporta límite alcanzado (bloqueo #{bloqueos}); "
                      f"espero {dormir // 60} min", flush=True)
                time.sleep(dormir)
                limitador.marcas.clear()
                continue
            raise RuntimeError(f"Error de la API: {msg}")
        if not isinstance(data, dict):
            raise RuntimeError(f"Respuesta inesperada de la API: {str(data)[:200]}")

        if ruta_cache:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(ruta_cache, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        return data


def poligono_a_wkt(poligono):
    """Convierte la lista [{'x': lon, 'y': lat}, ...] a WKT POLYGON."""
    if not poligono or len(poligono) < 3:
        return None
    pts = [(float(v["x"]), float(v["y"])) for v in poligono]
    if pts[0] != pts[-1]:
        pts.append(pts[0])          # WKT exige anillo cerrado
    coords = ", ".join(f"{x} {y}" for x, y in pts)
    return f"POLYGON (({coords}))"


def tile_de(lon, lat, z):
    """Tile XYZ (esquema Web Mercator, como OSM) que contiene un punto."""
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    lat_r = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)
    return x, y


def limites_tile(x, y, z):
    """(lon_min, lat_min, lon_max, lat_max) de un tile XYZ."""
    n = 2 ** z
    lon_min = x / n * 360 - 180
    lon_max = (x + 1) / n * 360 - 180
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon_min, lat_min, lon_max, lat_max


def tiles_que_cubren(bbox, z):
    """Todos los tiles de zoom z que intersectan el bbox."""
    lon_min, lat_min, lon_max, lat_max = bbox
    x0, y0 = tile_de(lon_min, lat_max, z)     # esquina NO -> x,y minimos
    x1, y1 = tile_de(lon_max, lat_min, z)     # esquina SE -> x,y maximos
    return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def zoom_inicial(bbox):
    """Menor zoom en el que el bbox abarca al menos 4 tiles en su eje largo.

    Asi el arranque cuesta pocos requests y la subdivision por 'found'
    hace el resto. AMBA -> z10 (16 tiles); Argentina -> z8 (~400 tiles).
    """
    lon_min, lat_min, lon_max, lat_max = bbox
    for z in range(1, 15):
        x0, y0 = tile_de(lon_min, lat_max, z)
        x1, y1 = tile_de(lon_max, lat_min, z)
        if max(x1 - x0, y1 - y0) + 1 >= 4:
            return z
    return 14


def recolectar(clave, x, y, z, limitador, encontrados, profundidad=0):
    """Recorre un tile, partiendolo en sus 4 hijos si trae demasiados objetos."""
    sangria = "  " * profundidad
    lon_min, lat_min, lon_max, lat_max = limites_tile(x, y, z)

    primera = consultar(clave, x, y, z, 1, limitador)
    total = int(primera.get("found", 0))
    print(f"{sangria}tile z{z} {x},{y} "
          f"({lon_min:.3f},{lat_min:.3f},{lon_max:.3f},{lat_max:.3f}) "
          f"-> {total} objetos", flush=True)

    if total == 0:
        return

    if total > UMBRAL_SUBDIVISION and profundidad < PROFUNDIDAD_MAX:
        for dx in (0, 1):
            for dy in (0, 1):
                recolectar(clave, 2 * x + dx, 2 * y + dy, z + 1,
                           limitador, encontrados, profundidad + 1)
        return

    paginas = math.ceil(total / MAX_POR_PAGINA)
    for pagina in range(1, paginas + 1):
        data = primera if pagina == 1 else consultar(clave, x, y, z, pagina, limitador)
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
    ap.add_argument("--zoom", type=int,
                    help="zoom inicial de los tiles (por defecto se calcula del bbox)")
    ap.add_argument("--cache", default="data/raw/wikimapia_cache",
                    help="directorio para guardar cada respuesta de la API y poder "
                         "reanudar sin gastar cuota ('' para desactivar)")
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

    global CACHE_DIR
    if args.cache:
        CACHE_DIR = os.path.join(args.cache, f"{etiqueta}_{time.strftime('%Y%m%d')}")

    print(f"Extrayendo categoría {CATEGORIA_BARRIOS_CERRADOS} sobre '{etiqueta}'")
    print(f"bbox: {bbox}")
    print(f"cache de respuestas: {CACHE_DIR or '(desactivada)'}")
    print()

    encontrados = {}
    inicio = time.time()
    z0 = args.zoom if args.zoom is not None else zoom_inicial(bbox)
    tiles = tiles_que_cubren(bbox, z0)
    print(f"zoom inicial {z0}: {len(tiles)} tiles cubren la región")
    print()
    limitador = Limitador()
    for x, y in tiles:
        recolectar(args.clave, x, y, z0, limitador, encontrados)

    # Los tiles del borde se pasan del bbox pedido. Nos quedamos solo con
    # los objetos cuyo centro (location.lat/lon) cae dentro del bbox, que es
    # lo que devolvería una consulta por área bien hecha.
    lon_min, lat_min, lon_max, lat_max = bbox
    fuera = 0
    for oid in list(encontrados):
        r = encontrados[oid]
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
        except (TypeError, ValueError):
            continue                     # sin centro: lo dejamos
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
            del encontrados[oid]
            fuera += 1

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
    print(f"  descartados por centro fuera del bbox: {fuera}")
    print(f"  sin polígono:   {sin_poligono}")
    print(f"  CSV:      {base}.csv")
    print(f"  GeoJSON:  {base}.geojson")

    if args.comparar:
        comparar_con_2022(registros, args.comparar)


if __name__ == "__main__":
    main()
