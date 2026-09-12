"""Arma la serie histórica 2015-2025 de los Estudios Anuales de CACE.

Las cifras salen de los resúmenes públicos (PDF) de cada estudio, que están en
data/raw/cace/ (bajados de cace.org.ar/pages/biblioteca-de-estudios), y del
comunicado de prensa de 2025. Cada fila lleva la URL del documento de donde
sale. Escribe el formato largo (una fila por indicador y año) y una tabla
ancha (una fila por año) en data/cace/.
"""
import csv, os

CDN = "https://cdn.shopify.com/s/files/1/0598/0176/3934/files/"
PDF = {2016: "2016_anual_resumen.pdf", 2017: "2017_anual_resumen.pdf", 2018: "2018_anual_resumen.pdf",
       2019: "2019_anual_resumen.pdf", 2020: "2020_anual_resumen.pdf", 2021: "2021_anual_resumen.pdf",
       2022: "Estudio_Anual_2022_CACE_resumen.pdf", 2023: "2023_reporte_prensa.pdf",
       2024: "2024_anual_prensa.pdf", 2025: "2025_anual_prensa.pdf"}
COMUNICADO_2025 = ("https://cace.org.ar/blogs/news/estudio-anual-de-cace-2025-el-ecommerce-como-"
                   "canal-estructural-del-consumo-argentino")
FECHA = "2026-09-09"

# (indicador, unidad, detalle, {año: valor})  -- fuente: PDF del año salvo que se indique
SERIES = [
    ("facturacion_total", "millones de pesos corrientes",
     "Monto total transaccionado (IVA incluido) declarado por empresas socias, B2C + C2C. "
     "2015 y los decimales de 2021-2023 salen de la serie del informe 2024 "
     "(los informes de cada año redondean: 1.520.000, 2.846.000, 7.829.000)",
     {2015: 68240, 2016: 102700, 2017: 156300, 2018: 229760, 2019: 403278, 2020: 905143,
      2021: 1520640, 2022: 2846154, 2023: 7829835, 2024: 22025462, 2025: 34033238}),
    ("crecimiento_facturacion_interanual", "%", "Variación nominal respecto del año anterior",
     {2016: 51, 2017: 52, 2018: 47, 2019: 76, 2020: 124, 2021: 68, 2022: 87, 2023: 175, 2024: 181, 2025: 55}),
    ("inflacion_interanual_indec", "%", "Inflación anual según INDEC tal como la cita el informe de CACE "
     "(2023 no la cita; IPC 2023 = 211,4 % según INDEC)",
     {2019: 53.8, 2020: 36.1, 2021: 50.9, 2022: 94.8, 2024: 117.7, 2025: 31.5}),
    ("ordenes_de_compra", "millones", "Transacciones con pago aprobado o autorizado",
     {2016: 47, 2017: 60, 2018: 79, 2019: 89, 2020: 164, 2021: 196, 2022: 211, 2023: 234, 2024: 246, 2025: 253}),
    ("crecimiento_ordenes_interanual", "%", "Variación de órdenes respecto del año anterior",
     {2017: 28, 2018: 32, 2019: 12, 2020: 84, 2021: 20, 2022: 8, 2023: 11, 2024: 5, 2025: 3}),
    ("unidades_vendidas", "millones", "Productos vendidos (en unidades)",
     {2016: 75, 2017: 96, 2018: 120, 2019: 146, 2020: 251, 2021: 381, 2022: 422, 2023: 489, 2024: 504, 2025: 645}),
    ("ticket_promedio", "pesos corrientes", "Facturación sobre órdenes de compra, tal como lo publica CACE. "
     "En 2024 no cierra con los otros dos datos del mismo informe (22.025.462 / 246 = 89.535, no 92.341); "
     "los demás años reproducen el cociente",
     {2015: 1795, 2016: 2185, 2017: 2600, 2018: 2900, 2019: 4500, 2020: 5519, 2021: 7757,
      2022: 13488, 2023: 33457, 2024: 92341, 2025: 134519}),
    ("compradores_totales", "personas", "Compradores online acumulados; proyección sobre población "
     "conectada (INDEC)",
     {2019: 18773246, 2020: 20058206, 2021: 20742665, 2022: 21828205, 2023: 23247989,
      2024: 23784620, 2025: 25123572}),
    ("compradores_nuevos", "personas", "Personas que compraron online por primera vez en el año "
     "(2024: el informe dice 536.632 en una lámina y 536.642 en otra)",
     {2019: 828000, 2020: 1284960, 2021: 684459, 2022: 1085540, 2023: 1419784, 2024: 536632, 2025: 1338952}),
    ("frecuencia_compra_mensual_o_mas", "% de encuestados", "Compran online al menos una vez al mes "
     "(fase demanda)", {2020: 60, 2023: 60, 2024: 60, 2025: 60}),
    ("participacion_facturacion_amba", "% de la facturación", "Distribución de la facturación por zona "
     "declarada por las empresas (fase oferta). 2017 es el valor revisado que publica el informe 2018 "
     "(el informe 2017 decía 49 %); desde 2023 AMBA = CABA + GBA y el resto de la provincia de Buenos "
     "Aires va aparte. En 2025 AMBA sube 42 -> 52 mientras resto PBA cae 17 -> 5: la suma AMBA + PBA "
     "(59 -> 57) es la cantidad estable, el salto parece reasignación entre categorías",
     {2016: 44, 2017: 39, 2018: 37, 2019: 37, 2020: 38, 2021: 39, 2022: 38, 2023: 41, 2024: 42, 2025: 52}),
    ("participacion_facturacion_resto_pba", "% de la facturación", "Resto de la provincia de Buenos Aires",
     {2023: 17, 2024: 17, 2025: 5}),
    ("participacion_facturacion_litoral", "% de la facturación", "Litoral", {2024: 13, 2025: 12}),
    ("participacion_facturacion_centro", "% de la facturación", "Centro", {2023: 8, 2024: 8, 2025: 9}),
    ("participacion_facturacion_sur", "% de la facturación", "Sur", {2024: 8, 2025: 9}),
    ("participacion_facturacion_noa", "% de la facturación", "NOA", {2024: 7, 2025: 7}),
    ("participacion_facturacion_cuyo", "% de la facturación", "Cuyo", {2024: 5, 2025: 5}),
    ("envio_a_domicilio_ventas", "% de las ventas", "Logística de entrega declarada por las empresas "
     "(fase oferta; no incluye marketplaces ni turismo)",
     {2016: 47, 2017: 44, 2018: 39, 2019: 39, 2020: 56, 2021: 55, 2022: 53, 2023: 60, 2024: 61, 2025: 58}),
    ("retiro_en_punto_de_venta_ventas", "% de las ventas", "Ídem, retiro en tienda",
     {2016: 45, 2017: 50, 2018: 54, 2019: 50, 2020: 35, 2021: 37, 2022: 35, 2023: 30, 2024: 27, 2025: 29}),
    ("compradores_eligen_envio_domicilio", "% de compradores", "Preferencia declarada por los compradores "
     "(fase demanda; respuesta múltiple)",
     {2016: 66, 2018: 62, 2019: 65, 2020: 80, 2021: 76, 2022: 73, 2023: 72}),
    ("entregas_hasta_24h", "% de las entregas", "Entregas en el día más entregas en 24 hs, total país "
     "(fase oferta). 2016-2020: suma de las dos categorías; 2021-2025: 'neto hasta 24 hs' del informe",
     {2016: 21, 2017: 14, 2018: 19, 2019: 22, 2020: 24, 2021: 28, 2022: 27, 2023: 30, 2024: 33, 2025: 37}),
    ("entregas_amba_en_el_dia", "% de las entregas en AMBA", "Plazos de entrega por región (fase oferta)",
     {2019: 9, 2020: 18, 2021: 23, 2022: 20, 2023: 22, 2024: 22, 2025: 28}),
    ("entregas_amba_en_24h", "% de las entregas en AMBA", "Ídem, entregadas en 24 hs (sin contar el mismo día)",
     {2019: 17, 2020: 12, 2021: 14, 2022: 14, 2023: 16, 2024: 21, 2025: 17}),
    ("entregas_interior_en_el_dia", "% de las entregas en el interior", "Plazos de entrega por región",
     {2019: 8, 2020: 10, 2021: 9, 2022: 10, 2023: 9, 2024: 11, 2025: 13}),
    ("entregas_interior_en_24h", "% de las entregas en el interior", "Ídem, en 24 hs",
     {2019: 8, 2020: 6, 2021: 8, 2022: 10, 2023: 9, 2024: 10, 2025: 14}),
    ("pago_tarjeta_credito", "% de participación", "Participación en las ventas (fase oferta)",
     {2024: 74, 2025: 67}),
]
# Filas de 2025 que solo están en el comunicado de prensa
EXTRA_2025 = [
    ("compradores_cross_border", 47, "% de compradores", "Compraron productos del exterior; 37 % en 2024"),
    ("busqueda_online_antes_de_compra_fisica", 85, "% de consumidores", "Omnicanalidad"),
    ("empresas_con_ia", 62, "% de empresas", "Oferta: implementan IA en sus procesos"),
]
# Años cuyo dato sale de otro informe (serie retrospectiva o valor revisado)
FUENTE_ALTERNA = {("facturacion_total", 2015): 2024, ("ticket_promedio", 2015): 2016,
                  ("participacion_facturacion_amba", 2017): 2018, ("crecimiento_ordenes_interanual", 2017): 2018,
                  ("compradores_eligen_envio_domicilio", 2018): 2020,
                  ("entregas_amba_en_el_dia", 2019): 2021, ("entregas_amba_en_24h", 2019): 2021,
                  ("entregas_interior_en_el_dia", 2019): 2021, ("entregas_interior_en_24h", 2019): 2021,
                  ("entregas_amba_en_el_dia", 2020): 2021, ("entregas_amba_en_24h", 2020): 2021,
                  ("entregas_interior_en_el_dia", 2020): 2021, ("entregas_interior_en_24h", 2020): 2021,
                  ("entregas_hasta_24h", 2020): 2021, ("entregas_hasta_24h", 2021): 2023, ("entregas_hasta_24h", 2022): 2023,
                  ("retiro_en_punto_de_venta_ventas", 2021): 2022, ("participacion_facturacion_amba", 2019): 2020,
                  ("participacion_facturacion_litoral", 2024): 2024, ("participacion_facturacion_sur", 2024): 2024}

def fuente(ind, anio):
    return CDN + PDF[FUENTE_ALTERNA.get((ind, anio), anio)]

filas = []
for ind, unidad, detalle, datos in SERIES:
    for anio, valor in sorted(datos.items()):
        filas.append(dict(indicador=ind, valor=valor, unidad=unidad, periodo=anio, detalle=detalle,
                          fuente_url=fuente(ind, anio), fecha_acceso=FECHA))
for ind, valor, unidad, detalle in EXTRA_2025:
    filas.append(dict(indicador=ind, valor=valor, unidad=unidad, periodo=2025, detalle=detalle,
                      fuente_url=COMUNICADO_2025, fecha_acceso=FECHA))
filas.sort(key=lambda f: (f["periodo"], f["indicador"]))

os.makedirs("data/cace", exist_ok=True)
largo = "data/cace/cace_estudio_anual_serie_2015_2025.csv"
with open(largo, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["indicador", "valor", "unidad", "periodo", "detalle", "fuente_url", "fecha_acceso"])
    w.writeheader(); w.writerows(filas)

# Tabla ancha: una fila por año, los indicadores principales
anios = sorted({f["periodo"] for f in filas})
cols = [s[0] for s in SERIES]
ancha = "data/cace/cace_estudio_anual_serie_2015_2025_ancha.csv"
with open(ancha, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["periodo"] + cols)
    for a in anios:
        w.writerow([a] + [next((s[3][a] for s in SERIES if s[0] == c and a in s[3]), "") for c in cols])
print(f"{largo}: {len(filas)} filas; {ancha}: {len(anios)} años")

# Control aritmético: crecimiento declarado vs cociente de niveles, y ticket vs facturación / órdenes
S = {s[0]: s[3] for s in SERIES}
print("\nControl: crecimiento declarado vs calculado de los niveles (puntos porcentuales)")
for nivel, crec in (("facturacion_total", "crecimiento_facturacion_interanual"),
                    ("ordenes_de_compra", "crecimiento_ordenes_interanual")):
    for a, v in sorted(S[crec].items()):
        if a - 1 in S[nivel]:
            calc = (S[nivel][a] / S[nivel][a - 1] - 1) * 100
            marca = "" if abs(calc - v) < 1.5 else "  <-- revisar"
            print(f"  {crec} {a}: declarado {v}, calculado {calc:.1f}{marca}")
print("Control: ticket declarado vs facturación / órdenes")
for a, t in sorted(S["ticket_promedio"].items()):
    if a in S["facturacion_total"] and a in S["ordenes_de_compra"]:
        calc = S["facturacion_total"][a] / S["ordenes_de_compra"][a]
        marca = "" if abs(calc / t - 1) < 0.02 else "  <-- revisar"
        print(f"  {a}: declarado {t}, calculado {calc:,.0f}{marca}")
