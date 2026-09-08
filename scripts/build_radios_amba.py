#!/usr/bin/env python3
"""
Recorta la cartografía corregida de radios censales 2022 al AMBA, le pega los
atributos del censo (si ya se corrió scripts/descargar_censo.py) y verifica el
cruce con las urbanizaciones cerradas por código de radio.

    python scripts/build_radios_amba.py

Entrada:
  data/raw/radios_2022/radios-2022.parquet      GeoParquet nacional (66.502
                                                radios, WGS84). Es la "Base
                                                cartográfica de radios del
                                                censo 2022, primera versión
                                                revisada y corregida" de
                                                Gonzalo M. Rodríguez
                                                (CEUR-CONICET, CC BY-SA 2.5),
                                                tal como la redistribuye el
                                                dataset pedroorden/censoargentino
                                                en Hugging Face. Original:
                                                https://ri.conicet.gov.ar/handle/11336/238198
  data/processed/censo_2022_radios_amba.csv     opcional, atributos por radio
  data/processed/urbanizaciones_amba_2022.csv   opcional, para el control

Salida:
  data/processed/radios_amba_2022.geojson       radios del AMBA con censo
  data/processed/radios_amba_2022.parquet       idem, GeoParquet
  data/processed/radios_amba_2022_resumen.csv   control por partido
"""

import os
import sys

import geopandas as gpd
import pandas as pd

RAW = "data/raw/radios_2022/radios-2022.parquet"
OUT = "data/processed"
CENSO = os.path.join(OUT, "censo_2022_radios_amba.csv")
URB = os.path.join(OUT, "urbanizaciones_amba_2022.csv")

# Códigos INDEC de los 40 partidos del AMBA (provincia 06) + CABA entera (02).
# Verificados contra el catálogo del censo (censoargentino) y contra el
# cod_depto del dataset de urbanizaciones 2022 (que trae el prefijo de
# provincia: 6119 = Brandsen). Mismos partidos que scripts/build_amba.py.
AMBA_06 = {
    "028": "Almirante Brown", "035": "Avellaneda", "091": "Berazategui", "098": "Berisso",
    "119": "Brandsen", "126": "Campana", "134": "Cañuelas", "245": "Ensenada",
    "252": "Escobar", "260": "Esteban Echeverría", "266": "Exaltación de la Cruz",
    "270": "Ezeiza", "274": "Florencio Varela", "329": "General Las Heras",
    "364": "General Rodríguez", "371": "General San Martín", "408": "Hurlingham",
    "410": "Ituzaingó", "412": "José C. Paz", "427": "La Matanza", "441": "La Plata",
    "434": "Lanús", "490": "Lomas de Zamora", "497": "Luján", "525": "Marcos Paz",
    "515": "Malvinas Argentinas", "532": "Mercedes", "560": "Moreno", "568": "Morón",
    "638": "Pilar", "648": "Presidente Perón", "658": "Quilmes", "749": "San Fernando",
    "756": "San Isidro", "760": "San Miguel", "778": "San Vicente", "805": "Tigre",
    "840": "Tres de Febrero", "861": "Vicente López", "882": "Zárate",
}


def cod3(s):
    """Código de departamento a 3 dígitos, tolerando el prefijo de provincia
    ('6119' -> '119', '28' -> '028')."""
    return s.astype(str).str.strip().str.zfill(3).str[-3:]


def main():
    if not os.path.exists(RAW):
        sys.exit(f"Falta {RAW}. Bajarlo de "
                 "https://huggingface.co/datasets/pedroorden/censoargentino/resolve/main/radios-2022.parquet")
    g = gpd.read_parquet(RAW)
    print(f"Nacional: {len(g):,} radios | CRS {g.crs.to_string() if g.crs else 'sin CRS'}")
    if g.crs is None:
        g = g.set_crs("EPSG:4326")

    amba = g[((g.PROV == "06") & g.DEPTO.isin(AMBA_06)) | (g.PROV == "02")].copy()
    amba["id_geo"] = amba["COD_2022"].astype(str).str.zfill(9)
    amba["partido"] = amba.apply(lambda r: AMBA_06.get(r.DEPTO) if r.PROV == "06" else f"Comuna {int(r.DEPTO)}", axis=1)
    amba["provincia"] = amba["PROV"].map({"06": "Buenos Aires", "02": "CABA"})
    print(f"AMBA: {len(amba):,} radios en {amba.partido.nunique()} partidos/comunas")

    # Control contra los códigos que traen el censo y las urbanizaciones
    if os.path.exists(CENSO):
        c0 = pd.read_csv(CENSO, dtype=str)
        pares = c0[c0.cod_prov == "06"][["cod_depto", "departamento"]].drop_duplicates()
        desac = {c: (n, AMBA_06.get(c)) for c, n in zip(cod3(pares.cod_depto), pares.departamento)
                 if AMBA_06.get(c) != n}
        print(f"Control de códigos de partido vs catálogo del censo: {len(desac)} desacuerdos {desac or ''}")
    if os.path.exists(URB):
        u = pd.read_csv(URB)
        ref = dict(zip(cod3(u["cod_depto"]), u["departamento"]))
        desac = {c: (n, AMBA_06.get(c)) for c, n in ref.items() if AMBA_06.get(c) != n}
        print(f"Control de códigos de partido vs urbanizaciones 2022: {len(desac)} desacuerdos {desac or ''}")
        u["id_geo_redcode"] = u["cod_radio"].astype(str).str.zfill(9)
        hit = u["id_geo_redcode"].isin(amba["id_geo"])
        print(f"Urbanizaciones cuyo REDCODE existe en la cartografía 2022: {hit.sum()} de {len(u)} ({100*hit.mean():.1f} %)")

        # El REDCODE de Poblaciones no siempre es un radio 2022 (puede venir de
        # la cartografía 2010). Reasignamos el radio 2022 por posición: el
        # punto representativo del polígono de cada urbanización dentro del
        # radio. Es la clave correcta para cruzar con el censo 2022.
        ug = gpd.read_file(URB.replace(".csv", ".geojson"))
        pts = ug[["id", "geometry"]].copy()
        pts["geometry"] = pts.geometry.representative_point()
        sj = gpd.sjoin(pts, amba[["id_geo", "partido", "geometry"]], how="left", predicate="within")
        sj = sj.drop_duplicates("id").set_index("id")
        u["id_geo_2022"] = u["id"].map(sj["id_geo"])
        u["partido_radio_2022"] = u["id"].map(sj["partido"])
        u["coincide_redcode"] = u["id_geo_2022"] == u["id_geo_redcode"]
        sin = u["id_geo_2022"].isna().sum()
        print(f"Reasignación espacial al radio 2022: {len(u) - sin} de {len(u)} urbanizaciones caen en un radio "
              f"({sin} fuera de la cartografía); coinciden con el REDCODE: {u.coincide_redcode.sum()} "
              f"({100*u.coincide_redcode.mean():.1f} %)")
        u[["id", "nombre", "departamento", "id_geo_redcode", "id_geo_2022", "partido_radio_2022",
           "coincide_redcode"]].to_csv(os.path.join(OUT, "urbanizaciones_amba_2022_radio2022.csv"), index=False)
        print(f"  -> {OUT}/urbanizaciones_amba_2022_radio2022.csv")

    # Atributos del censo
    if os.path.exists(CENSO):
        c = pd.read_csv(CENSO, dtype={"id_geo": str, "cod_prov": str, "cod_depto": str})
        c["id_geo"] = c["id_geo"].str.zfill(9)
        cols = [x for x in c.columns if x not in ("cod_prov", "provincia", "cod_depto", "departamento")]
        amba = amba.merge(c[cols], on="id_geo", how="left")
        sin = amba["poblacion"].isna().sum()
        print(f"Radios del AMBA sin fila en el censo: {sin} de {len(amba)}")
    else:
        print(f"(sin {CENSO}: se escribe la geometría sola)")

    # Validez y área
    inval = (~amba.geometry.is_valid).sum()
    if inval:
        print(f"Geometrías inválidas: {inval}; se reparan con buffer(0)")
        amba["geometry"] = amba.geometry.buffer(0)
    amba["area_km2"] = amba.to_crs("EPSG:5347").area / 1e6   # POSGAR 2007 faja 5 (Buenos Aires)
    if "poblacion" in amba:
        amba["densidad_hab_km2"] = (amba["poblacion"] / amba["area_km2"]).round(1)

    amba = amba.drop(columns=[c for c in ("xmin", "ymin", "xmax", "ymax", "bbox") if c in amba])
    os.makedirs(OUT, exist_ok=True)
    amba.to_parquet(os.path.join(OUT, "radios_amba_2022.parquet"), index=False)
    amba.to_file(os.path.join(OUT, "radios_amba_2022.geojson"), driver="GeoJSON")

    res = amba.groupby(["provincia", "partido"]).agg(radios=("id_geo", "size"), area_km2=("area_km2", "sum"))
    if "poblacion" in amba:
        res["poblacion"] = amba.groupby(["provincia", "partido"])["poblacion"].sum()
        res["densidad_hab_km2"] = (res["poblacion"] / res["area_km2"]).round(0)
        res["POB_TOT_P_cartografia"] = amba.groupby(["provincia", "partido"])["POB_TOT_P"].sum()
    res = res.round(2).reset_index().sort_values("radios", ascending=False)
    res.to_csv(os.path.join(OUT, "radios_amba_2022_resumen.csv"), index=False)
    print(f"\nSalida: {OUT}/radios_amba_2022.geojson / .parquet / _resumen.csv")
    print(res.head(12).to_string(index=False))


if __name__ == "__main__":
    main()
