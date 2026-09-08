# Delivery con drones en el AMBA

Trabajo Final de Maestría — Master in Management + Analytics, Universidad
Torcuato Di Tella. Track Investigación Aplicada, cohorte 2026.

**Pregunta de investigación:** ¿en qué zonas del AMBA y bajo qué condiciones
el delivery con drones tiene un costo por entrega inferior al del reparto
terrestre, y qué volumen mínimo diario necesita una ruta para amortizar la
inversión en un hub?

## Estructura

```
scripts/     código de extracción y procesamiento
data/raw/    datasets originales, sin modificar (no versionados)
data/processed/  derivados reproducibles (no versionados)
notebooks/   análisis exploratorio
docs/        entregables del seminario
```

`data/` está en `.gitignore` a propósito. El repositorio versiona el código,
no los datos: los derivados se regeneran corriendo los scripts contra
`data/raw/`. Si borrás `data/processed/` entero, tiene que poder reconstruirse
sin intervención manual.

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # completar WIKIMAPIA_KEY
```

## Scripts

### `scripts/extraer_wikimapia.py`

Extrae urbanizaciones cerradas (categoría 55191) desde la API de Wikimapia,
replicando la metodología de De Grande (2022) para obtener un corte
actualizado. Subdivide el área de forma recursiva cuando un bounding box
devuelve demasiados objetos, respeta el límite de 100 requests cada 5 minutos
y recalcula la superficie proyectando cada polígono a una cónica de igual área
centrada en su propio centroide.

```bash
export WIKIMAPIA_KEY="tu-clave"
python scripts/extraer_wikimapia.py --region amba \
  --salida data/processed \
  --comparar data/raw/Urbanizaciones_cerradas__2022.csv
```

Regiones predefinidas: `amba`, `corredor_norte`, `delta_tigre`, `argentina`.
También acepta `--bbox lon_min,lat_min,lon_max,lat_max`.

La clave se pide en <https://wikimapia.org/api/?action=my_keys> y queda atada a
un dominio; si figura como *not verified*, la API aplica el límite de la clave
de ejemplo (un request cada 30 segundos).

### `scripts/build_amba.py`

Toma el dataset de Poblaciones 2022 y genera el subconjunto del AMBA en CSV y
GeoJSON más un resumen por partido. Valida que todas las geometrías sean
polígonos válidos antes de escribir.

```bash
python scripts/build_amba.py
```

## Fuentes de datos

| Fuente | Licencia | Estado |
|---|---|---|
| Urbanizaciones cerradas 2022 — Poblaciones (De Grande), vía Wikimapia | CC BY 4.0 | En mano |
| Censo 2022 por radio censal — INDEC (REDATAM) | Uso público con cita | Pendiente |
| Cartografía de radios corregida — Rodríguez, CEUR-CONICET | CC BY-SA 2.5 | Pendiente |
| Series horarias de viento y precipitación — SMN | A confirmar | Pendiente |
| Red vial y edificios — OpenStreetMap | ODbL | Pendiente |
| Espacio aéreo y zonas restringidas — ANAC / EANA | Uso público | Pendiente |
| Penetración de e-commerce — CACE | Uso público con cita | Pendiente |
| Órdenes históricas de un operador | Privada, sujeta a NDA | En gestión |

**Los datos de operador no se versionan en este repositorio bajo ninguna
circunstancia.** Contienen direcciones de clientes. `data/operador/` está en
`.gitignore`; si llegan a incorporarse, va únicamente la versión geocodificada
y agregada, nunca las direcciones en texto.

## Notas metodológicas

El dataset de urbanizaciones proviene de Wikimapia, de cobertura colaborativa
y no censal: el listado no es exhaustivo y el sesgo probablemente favorece
urbanizaciones grandes y conocidas. Al comparar un corte nuevo contra el de
2022, parte de los identificadores nuevos corresponden a urbanizaciones que ya
existían y que nadie había cargado. El delta mide crecimiento del registro
colaborativo, no obra nueva; separar ambos efectos requiere validar una
muestra contra imágenes satelitales históricas.

## Referencias

- Aurambout, J.-P., Gkoumas, K. & Ciuffo, B. (2019). Last mile delivery by
  drones: an estimation of viable market potential and access to citizens
  across European cities. *European Transport Research Review*, 11:30.
- Murray, C. C. & Chu, A. G. (2015). The flying sidekick traveling salesman
  problem: Optimization of drone-assisted parcel delivery. *Transportation
  Research Part C*, 54, 86-109.
- De Grande, P. (2022). Urbanizaciones cerradas, 2022. Poblaciones.
  <https://poblaciones.org/@115501>

## Licencia

Código bajo licencia MIT. Los datasets de terceros conservan sus licencias
originales, detalladas en la tabla de fuentes.
