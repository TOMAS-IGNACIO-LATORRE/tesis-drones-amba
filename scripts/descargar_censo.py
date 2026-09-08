#!/usr/bin/env python3
"""
Descarga del Censo 2022 (INDEC, 1ª entrega definitiva) por radio censal para
el AMBA, vía el paquete `censoargentino` (DuckDB sobre Parquet remoto en
Hugging Face, dataset pedroorden/censoargentino).

Genera:
  data/raw/censo_2022/<prov>_<VARIABLE>.parquet   respuesta cruda en formato
                                                  largo, una por variable y
                                                  provincia (cache: no se
                                                  vuelve a bajar si existe)
  data/processed/censo_2022_radios_amba.csv       una fila por radio censal
                                                  del AMBA con población,
                                                  hogares, viviendas y
                                                  proxies de demanda
  data/processed/censo_2022_partidos_amba.csv     agregado por partido/comuna

Uso:
    python scripts/descargar_censo.py            # AMBA (40 partidos + CABA)
    python scripts/descargar_censo.py --todo-ba  # toda la provincia + CABA

Fuente: INDEC, Censo Nacional de Población, Hogares y Viviendas 2022,
resultados definitivos por radio (REDATAM). Uso público con cita.
Referencia de variables:
https://redatam.indec.gob.ar/redarg/CENSOS/CPV2022/Docs/Redatam_Definiciones_de_la_base_de_datos.pdf

Clave de cruce: `id_geo` es el código INDEC de radio de 9 caracteres
(prov 2 + depto 3 + fracción 2 + radio 2), CON cero a la izquierda para
Buenos Aires (06) y CABA (02). El REDCODE del dataset de urbanizaciones lo
trae como entero: hay que rellenarlo a 9 con ceros antes de cruzar.
"""

import argparse
import os
import sys
import time
import unicodedata

import pandas as pd

RAW = "data/raw/censo_2022"
OUT = "data/processed"

PROVINCIAS = {"06": "Buenos Aires", "02": "Ciudad Autónoma De Buenos Aires"}

# Mismos 40 partidos que scripts/build_amba.py (Gran Buenos Aires ampliado)
AMBA_PARTIDOS = {
    'Almirante Brown', 'Avellaneda', 'Berazategui', 'Berisso', 'Brandsen',
    'Campana', 'Cañuelas', 'Ensenada', 'Escobar', 'Esteban Echeverría',
    'Exaltación de la Cruz', 'Ezeiza', 'Florencio Varela', 'General Las Heras',
    'General Rodríguez', 'General San Martín', 'Hurlingham', 'Ituzaingó',
    'José C. Paz', 'La Matanza', 'La Plata', 'Lanús', 'Lomas de Zamora',
    'Luján', 'Marcos Paz', 'Malvinas Argentinas', 'Mercedes', 'Moreno',
    'Morón', 'Pilar', 'Presidente Perón', 'Quilmes', 'San Fernando',
    'San Isidro', 'San Miguel', 'San Vicente', 'Tigre', 'Tres de Febrero',
    'Vicente López', 'Zárate',
}

# Variables y para qué sirven en la tesis
VARIABLES = {
    "PERSONA_P02":     "población total (suma de sexos)",
    "PERSONA_EDADGRU": "estructura etaria (grandes grupos)",
    "HOGAR_TOTPOBH":   "hogares y personas por hogar (unidad de entrega)",
    "HOGAR_NBI_TOT":   "hogares con NBI (proxy socioeconómico)",
    "HOGAR_INMAT":     "calidad de materiales (proxy socioeconómico)",
    "HOGAR_H24A":      "hogares con internet en la vivienda",
    "HOGAR_H24B":      "hogares con celular con internet",
    "VIVIENDA_V01":    "tipo de vivienda: casa vs departamento (zona de entrega)",
    "VIVIENDA_V02":    "viviendas con y sin personas presentes (vacancia / uso temporario)",
    "VIVIENDA_URP":    "área urbana / rural del radio",
}


def sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s))
                   if unicodedata.category(c) != "Mn").lower().strip()


def clave_robusta(s):
    """Clave de comparación que sobrevive al mojibake del catálogo del censo
    ('Ca˝uelas', 'Esteban Echeverrķa', 'LujŠn'): minúsculas y solo ASCII, sin
    transliterar. 'Cañuelas' y 'Ca˝uelas' dan las dos 'cauelas'."""
    s = str(s).lower().strip()
    s = "".join(c for c in s if c.isascii())
    return " ".join(s.split())


def bajar(censo, prov_cod, prov_nombre, variable):
    """Devuelve el formato largo de una variable para una provincia, con cache."""
    ruta = os.path.join(RAW, f"{prov_cod}_{variable}.parquet")
    if os.path.exists(ruta):
        return pd.read_parquet(ruta)
    t0 = time.time()
    df = censo.query(variables=variable, provincia=prov_nombre)
    df["id_geo"] = df["id_geo"].astype(str).str.zfill(9)
    df.to_parquet(ruta, index=False)
    print(f"  {prov_cod} {variable:17s} {len(df):>9,} filas  {time.time()-t0:5.1f}s", flush=True)
    return df


def pivot(df, variable, etiquetas=None, prefijo=None):
    """Formato largo -> una columna por categoría (conteo), indexado por id_geo."""
    sub = df[df["codigo_variable"] == variable]
    if etiquetas is not None:
        sub = sub[sub["etiqueta_categoria"].isin(etiquetas)]
    w = sub.pivot_table(index="id_geo", columns="etiqueta_categoria",
                        values="conteo", aggfunc="sum", fill_value=0)
    if prefijo:
        w.columns = [f"{prefijo}_{sin_acentos(c).replace(' ', '_').replace('/', '')}" for c in w.columns]
    return w


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--todo-ba", action="store_true",
                    help="no filtrar por partidos del AMBA (toda la provincia + CABA)")
    args = ap.parse_args()

    import censoargentino as censo   # importa tarde: imprime al cargar el catálogo

    os.makedirs(RAW, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    # --- códigos de departamento del AMBA -----------------------------------
    # El catálogo del censo trae los nombres con la codificación rota
    # ('Ca˝uelas', 'LujŠn'), así que se compara con una clave solo-ASCII y
    # después se cruza contra los códigos que trae el dataset de
    # urbanizaciones 2022 (cod_depto) como control.
    deptos_ba = censo.departamentos("Buenos Aires")
    deptos_ba["codigo"] = deptos_ba["codigo"].astype(str).str.zfill(3)
    deptos_ba["clave"] = deptos_ba["departamento"].map(clave_robusta)
    canon = {clave_robusta(n): n for n in AMBA_PARTIDOS}
    amba_ba = deptos_ba[deptos_ba["clave"].isin(canon)].copy()
    faltan = set(canon) - set(amba_ba["clave"])
    if faltan:
        sys.exit(f"Partidos del AMBA sin código INDEC: {sorted(faltan)}")
    if len(amba_ba) != len(AMBA_PARTIDOS):
        sys.exit(f"Colisión de nombres: {len(amba_ba)} códigos para {len(AMBA_PARTIDOS)} partidos")
    amba_ba["departamento"] = amba_ba["clave"].map(canon)     # nombre limpio
    nombre_por_codigo = {"06": dict(zip(amba_ba["codigo"], amba_ba["departamento"]))}

    urb = os.path.join(OUT, "urbanizaciones_amba_2022.csv")
    if os.path.exists(urb):
        u = pd.read_csv(urb)
        # cod_depto trae el prefijo de provincia (6119 = Brandsen): últimos 3
        u["cod_depto"] = u["cod_depto"].astype(str).str.zfill(3).str[-3:]
        ref = dict(zip(u["cod_depto"], u["departamento"]))
        desac = {c: (ref[c], nombre_por_codigo["06"].get(c)) for c in ref
                 if nombre_por_codigo["06"].get(c) != ref[c]}
        print(f"Control de códigos contra urbanizaciones 2022: {len(ref)} partidos, "
              f"{len(desac)} desacuerdos {desac if desac else ''}")

    codigos_amba = {"06": set(amba_ba["codigo"]), "02": None}     # None = todas las comunas
    print(f"AMBA: {len(codigos_amba['06'])} partidos de Buenos Aires + 15 comunas de CABA")

    # --- descarga -----------------------------------------------------------
    print("\nDescargando (cache en", RAW + ")")
    largo = []
    for prov_cod, prov_nombre in PROVINCIAS.items():
        for variable in VARIABLES:
            df = bajar(censo, prov_cod, prov_nombre, variable)
            df["valor_departamento"] = df["valor_departamento"].astype(str).str.zfill(3)
            if not args.todo_ba and codigos_amba[prov_cod] is not None:
                df = df[df["valor_departamento"].isin(codigos_amba[prov_cod])]
            largo.append(df)
    largo = pd.concat(largo, ignore_index=True)

    # --- validación contra totales publicados --------------------------------
    print("\nControl: población por provincia (PERSONA_P02, todos los radios bajados)")
    for prov_cod, prov_nombre in PROVINCIAS.items():
        tot = pd.read_parquet(os.path.join(RAW, f"{prov_cod}_PERSONA_P02.parquet"))["conteo"].sum()
        print(f"  {prov_nombre:32s} {int(tot):>12,}")
    print("  (INDEC 2022 publicó ~17,57 M para Buenos Aires y ~3,12 M para CABA)")

    # --- tabla ancha por radio ----------------------------------------------
    geo = (largo.drop_duplicates("id_geo")
                .set_index("id_geo")[["valor_provincia", "etiqueta_provincia",
                                       "valor_departamento", "etiqueta_departamento"]])
    # etiqueta_departamento viene como código en la 1ª entrega; ponemos el nombre
    # (limpio para el AMBA; el del catálogo, con su mojibake, para el resto)
    ba_nombres = deptos_ba[["codigo", "departamento"]].copy()
    ba_nombres["departamento"] = ba_nombres["codigo"].map(nombre_por_codigo["06"]).fillna(ba_nombres["departamento"])
    caba = censo.departamentos("Ciudad Autónoma De Buenos Aires")
    caba["codigo"] = caba["codigo"].astype(str).str.zfill(3)
    nombres = pd.concat([
        ba_nombres.assign(valor_provincia="06")[["valor_provincia", "codigo", "departamento"]],
        caba.assign(valor_provincia="02")[["valor_provincia", "codigo", "departamento"]],
    ])
    geo = geo.reset_index().merge(nombres, left_on=["valor_provincia", "valor_departamento"],
                                  right_on=["valor_provincia", "codigo"], how="left")
    geo = geo.set_index("id_geo")[["valor_provincia", "etiqueta_provincia",
                                   "valor_departamento", "departamento"]]
    geo.columns = ["cod_prov", "provincia", "cod_depto", "departamento"]

    p02 = largo[largo.codigo_variable == "PERSONA_P02"].groupby("id_geo")["conteo"].sum().rename("poblacion")
    hog = largo[largo.codigo_variable == "HOGAR_TOTPOBH"].copy()
    hog["personas"] = hog["valor_categoria"].astype(int) * hog["conteo"]
    hogares = hog.groupby("id_geo").agg(hogares=("conteo", "sum"), personas_en_hogares=("personas", "sum"))
    hogares["personas_por_hogar"] = (hogares["personas_en_hogares"] / hogares["hogares"]).round(2)

    v02 = pivot(largo, "VIVIENDA_V02")
    v02.columns = ["viviendas_con_personas" if "Hay" in c else "viviendas_sin_personas" for c in v02.columns]
    v02["viviendas"] = v02.sum(axis=1)
    v02["pct_viviendas_sin_personas"] = (100 * v02["viviendas_sin_personas"] / v02["viviendas"]).round(1)

    v01 = pivot(largo, "VIVIENDA_V01", prefijo="viv")
    casas = v01.filter(like="viv_casa").sum(axis=1).rename("viv_casa")
    deptos = v01.filter(like="viv_departamento").sum(axis=1).rename("viv_departamento")
    tipo = pd.concat([casas, deptos], axis=1)
    tipo["pct_casas"] = (100 * tipo["viv_casa"] / v01.sum(axis=1)).round(1)

    nbi = pivot(largo, "HOGAR_NBI_TOT", prefijo="nbi")
    nbi_con = nbi.filter(regex="^nbi_.*con").sum(axis=1).rename("hogares_nbi")
    pct_nbi = (100 * nbi_con / nbi.sum(axis=1)).round(1).rename("pct_hogares_nbi")

    h24a = pivot(largo, "HOGAR_H24A", prefijo="internet")
    h24b = pivot(largo, "HOGAR_H24B", prefijo="celinternet")
    internet = h24a.filter(regex="internet_si").sum(axis=1).rename("hogares_internet")
    pct_internet = (100 * internet / h24a.sum(axis=1)).round(1).rename("pct_hogares_internet")
    cel = h24b.filter(regex="celinternet_si").sum(axis=1).rename("hogares_celular_internet")

    urp = largo[largo.codigo_variable == "VIVIENDA_URP"]
    urp = (urp.sort_values("conteo", ascending=False).drop_duplicates("id_geo")
              .set_index("id_geo")["etiqueta_categoria"].rename("area_urbano_rural"))

    edad = pivot(largo, "PERSONA_EDADGRU", prefijo="edad")

    ancha = (geo.join(p02).join(hogares).join(v02).join(tipo).join(nbi_con).join(pct_nbi)
                .join(internet).join(pct_internet).join(cel).join(urp).join(edad))
    ancha.index.name = "id_geo"
    ancha = ancha.reset_index().sort_values("id_geo")
    ruta = os.path.join(OUT, "censo_2022_radios_amba.csv")
    ancha.to_csv(ruta, index=False)

    # --- agregado por partido -----------------------------------------------
    num = ["poblacion", "hogares", "viviendas", "viviendas_sin_personas", "viv_casa",
           "viv_departamento", "hogares_nbi", "hogares_internet"]
    partidos = ancha.groupby(["cod_prov", "provincia", "cod_depto", "departamento"])[num].sum()
    partidos["radios"] = ancha.groupby(["cod_prov", "provincia", "cod_depto", "departamento"]).size()
    partidos["personas_por_hogar"] = (ancha.groupby(["cod_prov", "provincia", "cod_depto", "departamento"])
                                           ["personas_en_hogares"].sum() / partidos["hogares"]).round(2)
    partidos["pct_viviendas_sin_personas"] = (100 * partidos["viviendas_sin_personas"] / partidos["viviendas"]).round(1)
    partidos["pct_hogares_nbi"] = (100 * partidos["hogares_nbi"] / partidos["hogares"]).round(1)
    partidos = partidos.reset_index().sort_values("poblacion", ascending=False)
    partidos.to_csv(os.path.join(OUT, "censo_2022_partidos_amba.csv"), index=False)

    # --- cruce con las urbanizaciones 2022 por REDCODE -----------------------
    urb = os.path.join(OUT, "urbanizaciones_amba_2022.csv")
    if os.path.exists(urb):
        u = pd.read_csv(urb)
        u["id_geo"] = u["cod_radio"].astype(str).str.zfill(9)
        hit = u["id_geo"].isin(ancha["id_geo"])
        print(f"\nCruce urbanizaciones AMBA 2022 -> radios del censo: "
              f"{hit.sum()} de {len(u)} encuentran radio ({100*hit.mean():.1f} %)")
        if (~hit).any():
            print("  sin radio:", u.loc[~hit, ["id", "nombre", "departamento", "id_geo"]].head(10).to_string(index=False))

    print(f"\nRadios: {len(ancha):,} | población AMBA: {int(ancha.poblacion.sum()):,} | "
          f"hogares: {int(ancha.hogares.sum()):,} | viviendas: {int(ancha.viviendas.sum()):,}")
    print(f"CSV por radio:    {ruta}")
    print(f"CSV por partido:  {os.path.join(OUT, 'censo_2022_partidos_amba.csv')}")
    print()
    print(partidos[["departamento", "radios", "poblacion", "hogares", "personas_por_hogar",
                    "pct_viviendas_sin_personas", "pct_hogares_nbi"]].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
