import os
import json
import pandas as pd
from shapely import wkt

SRC = os.environ.get("SRC", "data/raw/Urbanizaciones_cerradas__2022.csv")
OUT = os.environ.get("OUT", "data/processed")

COLS = ['id', 'nombre', 'url', 'wkt', 'cod_prov', 'provincia', 'cod_depto',
        'departamento', 'cod_radio', 'sup_km2', 'lat', 'lon']

# 40 partidos del AMBA (definición INDEC/Gran Buenos Aires ampliado)
AMBA = {
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

os.makedirs(OUT, exist_ok=True)
df = pd.read_csv(SRC)
df.columns = COLS

ba = df[df.provincia.str.contains('Buenos Aires', na=False)].copy()
amba = ba[ba.departamento.isin(AMBA)].copy()
amba = amba.sort_values(['departamento', 'nombre']).reset_index(drop=True)

# Chequeos de integridad sobre el subconjunto
geoms = [wkt.loads(s) for s in amba.wkt]
assert all(g.is_valid for g in geoms), "hay geometrias invalidas"

amba.to_csv(f"{OUT}/urbanizaciones_amba_2022.csv", index=False)

features = []
for (_, r), g in zip(amba.iterrows(), geoms):
    features.append({
        "type": "Feature",
        "geometry": json.loads(json.dumps(g.__geo_interface__)),
        "properties": {
            "id": int(r.id),
            "nombre": r.nombre,
            "url": r.url,
            "provincia": r.provincia,
            "departamento": r.departamento,
            "cod_radio": int(r.cod_radio),
            "sup_km2": float(r.sup_km2),
            "lat": float(r.lat),
            "lon": float(r.lon),
        },
    })

with open(f"{OUT}/urbanizaciones_amba_2022.geojson", "w", encoding="utf-8") as f:
    json.dump({"type": "FeatureCollection",
               "crs": {"type": "name",
                       "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
               "features": features}, f, ensure_ascii=False)

# Resumen por partido
resumen = (amba.groupby('departamento')
                .agg(cantidad=('id', 'size'),
                     sup_total_km2=('sup_km2', 'sum'),
                     sup_mediana_km2=('sup_km2', 'median'))
                .round(3))
# Desempate por nombre para que el CSV sea byte a byte reproducible
resumen = resumen.sort_values(['cantidad', 'departamento'], ascending=[False, True])
resumen.to_csv(f"{OUT}/resumen_por_partido.csv")

print("Total nacional:", len(df))
print("Buenos Aires:", len(ba))
print("AMBA:", len(amba), "| partidos con registros:", amba.departamento.nunique())
print("Superficie AMBA km2:", round(amba.sup_km2.sum(), 2))
print()
print(resumen.head(15).to_string())
