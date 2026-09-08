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
actualizado. Recorre la región por tiles XYZ (`function=box` con `x,y,z`),
parte un tile en sus cuatro hijos cuando devuelve demasiados objetos, respeta
el límite de 100 requests cada 5 minutos y recalcula la superficie proyectando
cada polígono a una cónica de igual área centrada en su propio centroide.

Por qué tiles y no bounding boxes (verificado en septiembre de 2026):
`place.getbyarea` devuelve una lista vacía para cualquier consulta, y
`function=box` con `bbox` elige internamente un único tile según el centro de
la caja, así que pierde todo lo que queda fuera de ese tile (el bbox del delta
de Tigre devolvía 1 objeto; por tiles devuelve 92). Por `x,y,z` la respuesta
es exacta: cada objeto cae en un único tile y los cuatro hijos de un tile
suman exactamente el padre.

```bash
export WIKIMAPIA_KEY="tu-clave"
python scripts/extraer_wikimapia.py --region amba \
  --salida data/processed \
  --comparar data/raw/Urbanizaciones_cerradas__2022.csv
```

Regiones predefinidas: `amba`, `corredor_norte`, `delta_tigre`, `argentina`.
También acepta `--bbox lon_min,lat_min,lon_max,lat_max`. El zoom inicial de
los tiles se calcula del tamaño del bbox (AMBA arranca en z10, 25 tiles);
`--zoom N` lo fuerza. Los tiles del borde exceden el bbox: al final se
descartan los objetos cuyo centro cae fuera del área pedida.

La clave se puede dejar en `.env` como `WIKIMAPIA_KEY`
(`set -a; . ./.env; set +a` antes de correr) o pasar con `--clave`.

Cuota: el límite nominal es 100 requests cada 5 minutos, pero superarlo
bloquea la clave por bastante más que eso (medido: más de 10 minutos) y cada
request rechazado parece extender el bloqueo. El script se mantiene en 50
por ventana, y si igual la API responde "Key limit has been reached" espera
con backoff (5, 10, 20... minutos) sin rendirse. Cada respuesta se guarda en
`data/raw/wikimapia_cache/<region>_<fecha>/`, así que una corrida
interrumpida se reanuda sin volver a gastar cuota; `--cache ''` lo desactiva.
No conviene hacer pruebas manuales contra la API con la misma clave mientras
corre una extracción.

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

| Fuente | Licencia | Estado | Script | Dónde queda |
|---|---|---|---|---|
| Urbanizaciones cerradas 2022 — Poblaciones (De Grande), vía Wikimapia | CC BY 4.0 | En mano (crudo + derivados) | `build_amba.py` | `data/raw/Urbanizaciones_cerradas__2022.*`, `data/processed/urbanizaciones_amba_2022.*` |
| Urbanizaciones cerradas 2026 — extracción propia de Wikimapia | CC BY-SA (Wikimapia) | Delta de Tigre listo; AMBA pendiente de cuota de la API | `extraer_wikimapia.py` | `data/processed/urbanizaciones_<region>_<fecha>.*` |
| Censo 2022 por radio censal — INDEC (1ª entrega definitiva, vía `censoargentino`) | Uso público con cita | En mano: 17.693 radios del AMBA | `descargar_censo.py` | `data/raw/censo_2022/*.parquet`, `data/processed/censo_2022_radios_amba.csv` |
| Cartografía de radios 2022 corregida — Rodríguez, CEUR-CONICET (copia redistribuida en HF `pedroorden/censoargentino`) | CC BY-SA 2.5 | En mano: 66.502 radios, recorte AMBA con censo pegado | `build_radios_amba.py` | `data/raw/radios_2022/radios-2022.parquet`, `data/processed/radios_amba_2022.*` |
| Viento horario — SMN datos abiertos (`datohorario`, 2023-01-01 a 2026-09-07, 10 estaciones del AMBA) | Ver condiciones SMN (a confirmar) | En mano: 1.338 de 1.346 días, 284.859 filas; los 8 días que faltan no existen en el servidor | `descargar_smn.py` | `data/raw/smn/datohorario/`, `data/processed/smn_horario_amba.*` |
| Viento y precipitación horaria — NOAA ISD-Lite (Aeroparque, Ezeiza, El Palomar, San Fernando, Observatorio) | Dominio público | En mano 2020-2025 | `descargar_isd.py` | `data/raw/noaa_isd_lite/`, `data/processed/isd_horario_amba.*` |
| Red vial y edificios — OpenStreetMap (Geofabrik, extracto 2026-09-07) | ODbL | En mano: recorte AMBA, 264.794 vías, 223.841 edificios | `osmium` (ver abajo) | `data/raw/osm/amba*.osm.pbf` |
| Aeródromos y helipuertos — OurAirports + distancias RAAC Parte 100 (ANAC) | Dominio público / uso público | En mano: 81 sitios, 137 zonas de restricción. Faltan polígonos CTR/TMA (AIP) | `build_espacio_aereo.py` | `data/raw/espacio_aereo/`, `data/processed/espacio_aereo_amba.geojson`, `docs/regulacion/raac_parte_100.pdf` |
| Penetración y ticket de e-commerce — CACE, Estudio Anual 2025 | Uso público con cita | En mano: cifras públicas del comunicado (el informe completo es para socios) | — (curado a mano, sí se versiona) | `data/cace/cace_estudio_anual_2025_cifras.csv` |
| Órdenes históricas de un operador | Privada, sujeta a NDA | En gestión | — | `data/operador/` (nunca versionado) |

Todo lo que está en `data/` se regenera corriendo los scripts en este orden:
`build_amba.py` → `descargar_censo.py` → `build_radios_amba.py` →
`build_espacio_aereo.py` → `descargar_isd.py` → `descargar_smn.py`. Los de
descarga son reanudables: no vuelven a pedir lo que ya está en disco.

### Notas por fuente

**Censo 2022.** `descargar_censo.py` baja 10 variables (población, personas
por hogar, tipo y ocupación de la vivienda, NBI, materiales, internet, área
urbano/rural, edad) para los 40 partidos del AMBA y las 15 comunas, y arma
una fila por radio. Control: la población por partido coincide exactamente
con el campo `POB_TOT_P` de la cartografía de CONICET. Ojo con la clave de
cruce: `id_geo` son 9 caracteres con cero adelante (`068050101`); el
`cod_depto` del dataset de urbanizaciones trae el prefijo de provincia
(`6119` = Brandsen) y el catálogo del censo tiene los nombres con la
codificación rota (`Ca˝uelas`), por eso los scripts comparan códigos y no
nombres.

**Radios 2022.** El `REDCODE` que trae Poblaciones no es un radio 2022: solo
el 22,7 % coincide con el radio que contiene a cada urbanización según la
cartografía corregida. `build_radios_amba.py` reasigna el radio por posición
y deja la clave correcta en
`data/processed/urbanizaciones_amba_2022_radio2022.csv` (`id_geo_2022`).
Usar esa columna, no `cod_radio`, para cruzar con el censo.

**Meteorología.** Los archivos horarios abiertos del SMN traen viento
(dirección y velocidad en km/h) pero no precipitación; ISD-Lite de NOAA trae
las dos cosas para las mismas estaciones aeronáuticas, en UTC y con el viento
en m/s. Umbral de referencia (Speedbird): 55 km/h. El servidor del SMN
responde lento y con errores 522 intermitentes; el script reintenta y marca
las fechas que no consiguió en `data/raw/smn/faltantes_<desde>_<hasta>.txt`
(un archivo por corrida). Conviene correr
un rango por proceso (2023, 2024, 2025-26) y al final consolidar todo con
`--solo-consolidar`.

Cobertura del SMN 2023-2026: Aeroparque, Observatorio, Ezeiza, El Palomar,
San Fernando, Morón y La Plata tienen el 99 % de las horas; Campo de Mayo,
Mariano Moreno y Merlo solo reportan de día (54 a 75 %). El viento medio
horario supera los 55 km/h en menos del 0,05 % de las horas en todas las
estaciones, y el percentil 95 está entre 17 y 28 km/h: la ventana operable la
van a definir la precipitación y las ráfagas, no el viento medio. En ISD-Lite
las estaciones argentinas no reportan precipitación horaria, solo el
acumulado de 6 h de los reportes sinópticos (00, 06, 12 y 18 UTC); entre el
10 % y el 32 % de esos reportes traen lluvia según la estación.

Control cruzado: el viento del SMN (hora local) y el de ISD-Lite (UTC menos
3) coinciden hora a hora en las cinco estaciones comunes, con correlación
0,995 a 0,998 y diferencia media cero sobre más de 20.000 horas por estación.
Son la misma observación por dos canales, así que se puede usar ISD-Lite para
la precipitación y el SMN para las estaciones que NOAA no distribuye (Morón,
La Plata, Campo de Mayo, Mariano Moreno, Merlo).

**OpenStreetMap.** Con `osmium` instalado (`brew install osmium-tool`):

```bash
curl -L -o data/raw/osm/argentina-latest.osm.pbf https://download.geofabrik.de/south-america/argentina-latest.osm.pbf
osmium extract --bbox -59.30,-35.20,-57.90,-34.15 --strategy=complete_ways -o data/raw/osm/amba.osm.pbf data/raw/osm/argentina-latest.osm.pbf
osmium tags-filter -o data/raw/osm/amba_vial.osm.pbf data/raw/osm/amba.osm.pbf w/highway
osmium tags-filter -o data/raw/osm/amba_edificios.osm.pbf data/raw/osm/amba.osm.pbf w/building
```

El recorte vial (16 MB) es la entrada para OSRM. No convertir el recorte
completo a GeoJSON: son cientos de miles de edificios.

**Espacio aéreo.** No existe una capa oficial. `build_espacio_aereo.py`
aplica las distancias de la RAAC 100 (3 NM alrededor de aeródromos con tope
de 150 ft; 1 NM prohibido y 1-2 NM con tope de 150 ft alrededor de
helipuertos) sobre los puntos de OurAirports. Con eso, el 24 % del recuadro
del AMBA queda bajo alguna restricción. Lo que falta y hay que decidir cómo
obtener: los polígonos CTR/TMA y los corredores VFR del AIP Argentina (EANA),
sea digitalizando las cartas o con OpenAIP (requiere cuenta, CC BY-NC-SA).
El PDF de la RAAC 100 en `docs/regulacion/` es la primera edición (abril
2025); verificar contra la Resolución 550/2025 y las 311-313/2026.

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
