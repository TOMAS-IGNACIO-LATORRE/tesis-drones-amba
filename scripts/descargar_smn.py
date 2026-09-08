#!/usr/bin/env python3
"""
Descarga las observaciones horarias del Servicio Meteorológico Nacional
(datos abiertos, archivo diario `datohorario<YYYYMMDD>.txt`) y consolida las
estaciones del AMBA en una sola tabla.

    python scripts/descargar_smn.py                       # 2023-01-01 -> ayer
    python scripts/descargar_smn.py --desde 2024-01-01 --hasta 2024-12-31
    python scripts/descargar_smn.py --solo-consolidar     # no baja nada

Salida:
  data/raw/smn/datohorario/datohorario<YYYYMMDD>.txt   crudo, latin-1, todas
                                                       las estaciones del país
  data/raw/smn/faltantes.txt                           fechas que el SMN no
                                                       tiene ("El archivo no
                                                       existe") o que fallaron
  data/processed/smn_horario_amba.parquet / .csv       estaciones del AMBA,
                                                       una fila por estación
                                                       y hora

Variables: TEMP [°C], HUM [%], PNM [hPa], DD dirección del viento [grados,
0 = calma], FF velocidad del viento [km/h]. No incluye precipitación: para
eso ver scripts/descargar_isd.py (NOAA ISD-Lite).

Notas:
- El archivo diario suele estar disponible desde 2020 en adelante. Fechas
  anteriores devuelven error 522 (Cloudflare) de forma intermitente.
- El servidor responde HTTP 200 con el texto "El archivo no existe." cuando
  falta el día: hay que mirar el cuerpo, no el código.
- Descarga reanudable: si el archivo ya está en disco no se vuelve a pedir.
- Fuente: SMN, https://www.smn.gob.ar/descarga-de-datos . Condiciones de
  uso: ver esa página (a confirmar en la tesis).
"""

import argparse
import datetime as dt
import os
import sys
import time

import pandas as pd
import requests

URL = "https://ssl.smn.gob.ar/dpd/descarga_opendata.php?file=observaciones/datohorario{fecha}.txt"
RAW = "data/raw/smn/datohorario"
FALTANTES = "data/raw/smn/faltantes.txt"
OUT = "data/processed/smn_horario_amba"

# Nombres tal como figuran en la columna NOMBRE de datohorario
ESTACIONES_AMBA = {
    "AEROPARQUE AERO", "BUENOS AIRES OBSERVATORIO", "EZEIZA AERO",
    "EL PALOMAR AERO", "SAN FERNANDO AERO", "MORON AERO", "LA PLATA AERO",
    "CAMPO DE MAYO AERO", "MARIANO MORENO AERO", "MERLO AERO",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (tesis MiM+A UTDT; datos abiertos SMN)"}


def descargar_dia(fecha, pausa, reintentos=3):
    """Devuelve 'ok', 'existente', 'no_existe' o 'error'."""
    ruta = os.path.join(RAW, f"datohorario{fecha}.txt")
    if os.path.exists(ruta) and os.path.getsize(ruta) > 1000:
        return "existente"
    espera = 5
    for intento in range(reintentos):
        try:
            r = requests.get(URL.format(fecha=fecha), headers=HEADERS, timeout=60)
        except requests.RequestException as e:
            print(f"    {fecha}: error de red ({e}); reintento en {espera} s", flush=True)
            time.sleep(espera); espera *= 2
            continue
        cuerpo = r.content
        if b"no existe" in cuerpo[:200]:
            return "no_existe"
        if r.status_code != 200 or len(cuerpo) < 1000 or cuerpo.lstrip().startswith(b"error code"):
            print(f"    {fecha}: http {r.status_code}, {len(cuerpo)} bytes; reintento en {espera} s", flush=True)
            time.sleep(espera); espera *= 2
            continue
        with open(ruta, "wb") as f:
            f.write(cuerpo)
        time.sleep(pausa)
        return "ok"
    return "error"


def parsear_archivo(ruta, estaciones=None):
    """Parsea un datohorario. Los campos numéricos van separados por espacios
    y el nombre de estación (con espacios) empieza en una columna fija que se
    lee del encabezado."""
    with open(ruta, encoding="latin-1") as f:
        lineas = f.read().splitlines()
    if len(lineas) < 3 or not lineas[0].startswith("FECHA"):
        return pd.DataFrame(), 0
    corte = lineas[0].index("NOMBRE") - 1        # el dato arranca 1 col antes
    filas, malas = [], 0
    for ln in lineas[2:]:
        if len(ln) < corte + 1:
            continue
        nombre = ln[corte:].strip()
        if estaciones and nombre not in estaciones:
            continue
        campos = ln[:corte].split()
        if len(campos) != 7:
            # valores faltantes en blanco: caemos a cortes fijos
            cortes = [(0, 8), (8, 14), (14, 20), (20, 26), (26, 33), (33, 38), (38, corte)]
            campos = [ln[a:b].strip() or None for a, b in cortes]
            if not campos[0] or not campos[1]:
                malas += 1
                continue
        filas.append(campos + [nombre])
    df = pd.DataFrame(filas, columns=["fecha", "hora", "temp", "hum", "pnm", "dd", "ff", "estacion"])
    return df, malas


def consolidar(desde, hasta):
    archivos = sorted(f for f in os.listdir(RAW) if f.startswith("datohorario") and f.endswith(".txt"))
    archivos = [f for f in archivos if desde <= f[11:19] <= hasta]
    partes, malas_tot = [], 0
    for f in archivos:
        df, malas = parsear_archivo(os.path.join(RAW, f), ESTACIONES_AMBA)
        malas_tot += malas
        if len(df):
            partes.append(df)
    if not partes:
        sys.exit("No hay archivos para consolidar en el rango.")
    df = pd.concat(partes, ignore_index=True)
    df["fecha"] = pd.to_datetime(df["fecha"], format="%d%m%Y", errors="coerce")
    for c in ("hora", "temp", "hum", "pnm", "dd", "ff"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["fecha_hora"] = df["fecha"] + pd.to_timedelta(df["hora"], unit="h")
    df = (df.dropna(subset=["fecha", "hora"])
            .drop_duplicates(["estacion", "fecha_hora"])
            .sort_values(["estacion", "fecha_hora"])
            [["estacion", "fecha_hora", "temp", "hum", "pnm", "dd", "ff"]])
    df.to_parquet(OUT + ".parquet", index=False)
    df.to_csv(OUT + ".csv", index=False)

    print(f"\nConsolidado: {len(archivos)} días, {len(df):,} filas, {malas_tot} líneas descartadas")
    print(f"  {OUT}.parquet / .csv")
    resumen = (df.groupby("estacion")
                 .agg(desde=("fecha_hora", "min"), hasta=("fecha_hora", "max"),
                      horas=("fecha_hora", "size"), ff_nulo_pct=("ff", lambda s: round(100 * s.isna().mean(), 1)),
                      ff_media_kmh=("ff", "mean"), ff_p95_kmh=("ff", lambda s: s.quantile(0.95)),
                      pct_horas_ff_mayor_55=("ff", lambda s: round(100 * (s > 55).mean(), 2))))
    dias = (df["fecha_hora"].max() - df["fecha_hora"].min()).days + 1
    resumen["cobertura_pct"] = (100 * resumen["horas"] / (24 * dias)).round(1)
    print(resumen.round(1).to_string())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", default="2023-01-01")
    ap.add_argument("--hasta", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--pausa", type=float, default=0.7, help="segundos entre requests")
    ap.add_argument("--solo-consolidar", action="store_true")
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    desde = dt.date.fromisoformat(args.desde)
    hasta = dt.date.fromisoformat(args.hasta)

    if not args.solo_consolidar:
        total = (hasta - desde).days + 1
        print(f"Descargando {total} días ({desde} -> {hasta}) en {RAW}", flush=True)
        estados = {"ok": 0, "existente": 0, "no_existe": 0, "error": 0}
        faltantes = []
        d = desde
        while d <= hasta:
            fecha = d.strftime("%Y%m%d")
            est = descargar_dia(fecha, args.pausa)
            estados[est] += 1
            if est in ("no_existe", "error"):
                faltantes.append(f"{fecha}\t{est}")
            n = sum(estados.values())
            if n % 50 == 0 or d == hasta:
                print(f"  {n}/{total}  {estados}", flush=True)
            d += dt.timedelta(days=1)
        with open(FALTANTES, "w") as f:
            f.write("\n".join(faltantes) + ("\n" if faltantes else ""))
        print(f"Faltantes: {len(faltantes)} (lista en {FALTANTES})")

    consolidar(desde.strftime("%Y%m%d"), hasta.strftime("%Y%m%d"))


if __name__ == "__main__":
    main()
