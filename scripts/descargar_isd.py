#!/usr/bin/env python3
"""
Descarga NOAA ISD-Lite (Integrated Surface Database, subconjunto horario) para
las estaciones sinópticas del AMBA y consolida viento y precipitación.

    python scripts/descargar_isd.py                  # 2020 -> año actual
    python scripts/descargar_isd.py --desde 2023 --hasta 2025

Salida:
  data/raw/noaa_isd_lite/<USAF>-<WBAN>-<AÑO>.gz       crudo, un archivo por
                                                      estación y año
  data/processed/isd_horario_amba.parquet / .csv      una fila por estación
                                                      y hora UTC

Por qué esta fuente además del SMN: los archivos horarios abiertos del SMN
no traen precipitación. ISD-Lite trae precipitación acumulada de 1 h y de
6 h, además de viento (m/s) y temperatura, para las mismas estaciones
(Aeroparque, Ezeiza, El Palomar, San Fernando, Observatorio). Es dominio
público (NOAA NCEI). Sirve también para cruzar el viento contra el del SMN.

Formato (isd-lite-format.txt): ancho fijo, hora UTC redondeada, valores
enteros escalados x10 salvo dirección del viento y nubosidad; -9999 = faltante.
"""

import argparse
import datetime as dt
import gzip
import io
import os
import time

import pandas as pd
import requests

URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-lite/{anio}/{usaf}-{wban}-{anio}.gz"
RAW = "data/raw/noaa_isd_lite"
OUT = "data/processed/isd_horario_amba"

ESTACIONES = {
    # USAF-WBAN: (nombre, OACI, lat, lon)   -- de isd-history.csv
    "875820-99999": ("AEROPARQUE JORGE NEWBERY", "SABE", -34.559, -58.416),
    "875850-99999": ("BUENOS AIRES OBSERVATORIO", "SABA", -34.583, -58.483),
    "875710-99999": ("EL PALOMAR", "SADP", -34.610, -58.613),
    "875760-99999": ("EZEIZA MINISTRO PISTARINI", "SAEZ", -34.822, -58.536),
    "875530-99999": ("SAN FERNANDO", "SADF", -34.453, -58.590),
    "875690-99999": ("SAN MIGUEL", "", -34.550, -58.733),
}

# (inicio, fin) 0-based, según isd-lite-format.txt (posiciones 1-based inclusivas)
COLSPECS = [(0, 4), (5, 7), (8, 11), (11, 13), (13, 19), (19, 25), (25, 31),
            (31, 37), (37, 43), (43, 49), (49, 55), (55, 61)]
NOMBRES = ["anio", "mes", "dia", "hora", "temp", "rocio", "pnm", "dd", "ff", "nubes", "pp_1h", "pp_6h"]


def descargar(usaf_wban, anio, reintentos=3):
    ruta = os.path.join(RAW, f"{usaf_wban}-{anio}.gz")
    if os.path.exists(ruta) and os.path.getsize(ruta) > 200:
        return ruta, "existente"
    usaf, wban = usaf_wban.split("-")
    espera = 5
    for _ in range(reintentos):
        try:
            r = requests.get(URL.format(anio=anio, usaf=usaf, wban=wban), timeout=120)
        except requests.RequestException:
            time.sleep(espera); espera *= 2
            continue
        if r.status_code == 404:
            return None, "no_existe"
        if r.status_code == 200 and len(r.content) > 200:
            with open(ruta, "wb") as f:
                f.write(r.content)
            return ruta, "ok"
        if r.status_code == 200:
            # NOAA publica archivos casi vacíos (El Palomar 2020 y 2021 traen
            # 4 y 7 horas en todo el año); no sirven y no es un error de red.
            return None, "vacio"
        time.sleep(espera); espera *= 2
    return None, "error"


def parsear(ruta, usaf_wban):
    with gzip.open(ruta, "rt") as f:
        df = pd.read_fwf(io.StringIO(f.read()), colspecs=COLSPECS, names=NOMBRES, header=None)
    df["fecha_hora_utc"] = pd.to_datetime(dict(year=df.anio, month=df.mes, day=df.dia, hour=df.hora))
    for c in ("temp", "rocio", "pnm", "dd", "ff", "nubes", "pp_1h", "pp_6h"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        df.loc[df[c] == -9999, c] = float("nan")
    for c in ("temp", "rocio", "pnm", "ff", "pp_1h", "pp_6h"):
        df[c] = df[c] / 10.0
    df["ff_kmh"] = (df["ff"] * 3.6).round(1)
    nombre, oaci, lat, lon = ESTACIONES[usaf_wban]
    df["estacion_id"] = usaf_wban
    df["estacion"] = nombre
    df["oaci"] = oaci
    return df[["estacion_id", "estacion", "oaci", "fecha_hora_utc", "temp", "rocio", "pnm",
               "dd", "ff", "ff_kmh", "nubes", "pp_1h", "pp_6h"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", type=int, default=2020)
    ap.add_argument("--hasta", type=int, default=dt.date.today().year)
    args = ap.parse_args()
    os.makedirs(RAW, exist_ok=True)

    partes = []
    for usaf_wban, (nombre, oaci, _, _) in ESTACIONES.items():
        for anio in range(args.desde, args.hasta + 1):
            ruta, est = descargar(usaf_wban, anio)
            print(f"  {nombre:28s} {anio}  {est}", flush=True)
            if ruta:
                partes.append(parsear(ruta, usaf_wban))
            time.sleep(0.3)
    df = pd.concat(partes, ignore_index=True).sort_values(["estacion_id", "fecha_hora_utc"])
    df.to_parquet(OUT + ".parquet", index=False)
    df.to_csv(OUT + ".csv", index=False)

    print(f"\nConsolidado: {len(df):,} filas -> {OUT}.parquet / .csv")
    res = (df.groupby(["estacion", "oaci"])
             .agg(desde=("fecha_hora_utc", "min"), hasta=("fecha_hora_utc", "max"), horas=("fecha_hora_utc", "size"),
                  ff_nulo_pct=("ff", lambda s: round(100 * s.isna().mean(), 1)),
                  ff_media_kmh=("ff_kmh", "mean"), ff_max_kmh=("ff_kmh", "max"),
                  pct_horas_ff_mayor_40=("ff_kmh", lambda s: round(100 * (s > 40).mean(), 2)),
                  pct_horas_ff_mayor_55=("ff_kmh", lambda s: round(100 * (s > 55).mean(), 2)),
                  # Las estaciones argentinas no reportan pp de 1 h: solo los
                  # acumulados de 6 h de los reportes sinópticos (00/06/12/18 UTC)
                  reportes_pp_6h=("pp_6h", lambda s: int(s.notna().sum())),
                  pct_reportes_6h_con_lluvia=("pp_6h", lambda s: round(100 * (s.dropna() > 0).mean(), 1)),
                  pp_6h_max_mm=("pp_6h", "max")))
    print(res.round(1).to_string())


if __name__ == "__main__":
    main()
