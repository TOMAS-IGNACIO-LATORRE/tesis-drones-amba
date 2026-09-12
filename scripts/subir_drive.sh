#!/usr/bin/env bash
# Sube las fuentes de datos a la carpeta "Checkpoint 1" de Google Drive con rclone.
#
# Requiere el remote `tesis` apuntando a la carpeta Checkpoint 1 (una sola vez,
# abre el navegador para autorizar con la cuenta latorretomas49@gmail.com):
#
#   rclone config create tesis drive scope=drive \
#       root_folder_id=1alNAM8hbxGALa6d-f_fhombrEgwP8j46
#
# Uso:
#   bash scripts/subir_drive.sh              # sube lo que falte o cambió
#   bash scripts/subir_drive.sh --dry-run    # muestra qué subiría
#
# Compara por checksum (Drive expone md5), así que lo que ya está igual no se
# vuelve a subir. Dentro de cada carpeta 0X_* se usa la misma convención que
# ya tiene 01_urbanizaciones_cerradas: `crudo/` para lo bajado sin tocar y
# `derivado/` para lo que generan los scripts (más el script que los genera).
# No sube argentina-latest.osm.pbf
# (429 MB, se regenera con curl) ni nada de data/operador/ (NDA).
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE="${REMOTE:-tesis}"
BASES="Bases de datos"
FLAGS=(--checksum --transfers 4 --checkers 4 --drive-chunk-size 32M
       --exclude .DS_Store --exclude .gitkeep --stats-one-line -v "$@")

if ! rclone listremotes | grep -qx "${REMOTE}:"; then
    echo "Falta el remote '${REMOTE}'. Crealo con:" >&2
    echo "  rclone config create ${REMOTE} drive scope=drive root_folder_id=1alNAM8hbxGALa6d-f_fhombrEgwP8j46" >&2
    exit 1
fi

# origen local -> carpeta destino (relativa a Checkpoint 1)
MAPA=(
  "data/raw/Urbanizaciones_cerradas__2022.csv|$BASES/01_urbanizaciones_cerradas/crudo"
  "data/raw/Urbanizaciones_cerradas__2022.sav|$BASES/01_urbanizaciones_cerradas/crudo"
  "data/raw/Urbanizaciones_cerradas__2022_-_Diccionario_de_datos.xlsx|$BASES/01_urbanizaciones_cerradas/crudo"
  "data/raw/Metadatos.docx|$BASES/01_urbanizaciones_cerradas/crudo"
  "data/processed/urbanizaciones_amba_2022.csv|$BASES/01_urbanizaciones_cerradas/derivado"
  "data/processed/urbanizaciones_amba_2022.geojson|$BASES/01_urbanizaciones_cerradas/derivado"
  "data/processed/urbanizaciones_amba_2022_radio2022.csv|$BASES/01_urbanizaciones_cerradas/derivado"
  "data/processed/resumen_por_partido.csv|$BASES/01_urbanizaciones_cerradas/derivado"
  "scripts/build_amba.py|$BASES/01_urbanizaciones_cerradas/derivado"
  "data/processed/urbanizaciones_delta_tigre_20260908.csv|$BASES/01_urbanizaciones_cerradas/wikimapia_2026"
  "data/processed/urbanizaciones_delta_tigre_20260908.geojson|$BASES/01_urbanizaciones_cerradas/wikimapia_2026"
  "scripts/extraer_wikimapia.py|$BASES/01_urbanizaciones_cerradas/wikimapia_2026"

  "data/raw/censo_2022|$BASES/02_censo_2022/crudo/censo_2022"
  "data/raw/radios_2022|$BASES/02_censo_2022/crudo/radios_2022"
  "data/processed/censo_2022_radios_amba.csv|$BASES/02_censo_2022/derivado"
  "data/processed/censo_2022_partidos_amba.csv|$BASES/02_censo_2022/derivado"
  "data/processed/radios_amba_2022.geojson|$BASES/02_censo_2022/derivado"
  "data/processed/radios_amba_2022.parquet|$BASES/02_censo_2022/derivado"
  "data/processed/radios_amba_2022_resumen.csv|$BASES/02_censo_2022/derivado"
  "scripts/descargar_censo.py|$BASES/02_censo_2022/derivado"
  "scripts/build_radios_amba.py|$BASES/02_censo_2022/derivado"

  "data/raw/noaa_isd_lite|$BASES/03_meteorologia_smn/crudo/noaa_isd_lite"
  "data/processed/smn_horario_amba.csv|$BASES/03_meteorologia_smn/derivado"
  "data/processed/smn_horario_amba.parquet|$BASES/03_meteorologia_smn/derivado"
  "data/processed/isd_horario_amba.csv|$BASES/03_meteorologia_smn/derivado"
  "data/processed/isd_horario_amba.parquet|$BASES/03_meteorologia_smn/derivado"
  "scripts/descargar_smn.py|$BASES/03_meteorologia_smn/derivado"
  "scripts/descargar_isd.py|$BASES/03_meteorologia_smn/derivado"

  "data/raw/osm/amba.osm.pbf|$BASES/04_red_vial_osm/crudo"
  "data/raw/osm/amba_vial.osm.pbf|$BASES/04_red_vial_osm/crudo"
  "data/raw/osm/amba_edificios.osm.pbf|$BASES/04_red_vial_osm/crudo"
  "data/raw/osm/extract.log|$BASES/04_red_vial_osm/crudo"

  "data/raw/espacio_aereo|$BASES/05_espacio_aereo_anac/crudo"
  "data/processed/espacio_aereo_amba.geojson|$BASES/05_espacio_aereo_anac/derivado"
  "data/processed/espacio_aereo_amba_resumen.csv|$BASES/05_espacio_aereo_anac/derivado"
  "data/processed/aerodromos_amba.geojson|$BASES/05_espacio_aereo_anac/derivado"
  "scripts/build_espacio_aereo.py|$BASES/05_espacio_aereo_anac/derivado"
  "docs/regulacion/raac_parte_100.pdf|$BASES/05_espacio_aereo_anac/crudo"

  "data/cace|$BASES/06_mercado_ecommerce/crudo"
  "data/raw/cace|$BASES/06_mercado_ecommerce/crudo/estudios_anuales_pdf"
  "scripts/build_cace_serie.py|$BASES/06_mercado_ecommerce/crudo"
)

for par in "${MAPA[@]}"; do
    origen="${par%%|*}"; destino="${par##*|}"
    if [ ! -e "$origen" ]; then
        echo "AVISO: no existe $origen, lo salto" >&2
        continue
    fi
    echo "== $origen -> $destino"
    rclone copy "$origen" "${REMOTE}:${destino}" "${FLAGS[@]}"
done

# El crudo del SMN son 1.338 archivos diarios (284 MB de texto): va comprimido
# en un solo zip, junto con la lista de fechas que el servidor no tiene.
if [ -d data/raw/smn/datohorario ]; then
    tmp="$(mktemp -d)"
    zip="$tmp/smn_datohorario_2023-01-01_2026-09-07.zip"
    echo "== data/raw/smn/datohorario -> $BASES/03_meteorologia_smn/crudo (zip)"
    (cd data/raw/smn && zip -q -X -r "$zip" datohorario faltantes_*.txt)
    rclone copy "$zip" "${REMOTE}:${BASES}/03_meteorologia_smn/crudo" "${FLAGS[@]}"
    rm -rf "$tmp"
fi

echo
echo "Listo. Árbol en Drive:"
rclone tree "${REMOTE}:${BASES}" --noreport -s --sort-size 2>/dev/null || rclone lsf -R "${REMOTE}:${BASES}"
