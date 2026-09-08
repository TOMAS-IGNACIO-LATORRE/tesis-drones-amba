#!/usr/bin/env bash
# Crea el repositorio en GitHub y sube el contenido de esta carpeta.
#
#   bash publicar_repo.sh
#
# Pide el token por entrada oculta: no queda en el historial de bash,
# no se escribe en disco y no se muestra en pantalla.
#
# Token: https://github.com/settings/tokens
#   - Fine-grained -> Only select repositories no sirve para crear uno nuevo,
#     asi que para el primer push usa "All repositories" con permiso
#     Administration: Read and write + Contents: Read and write.
#   - O un clasico con el scope "repo".
# Borralo apenas termines si no lo vas a reusar.

set -euo pipefail

USUARIO="TOMAS-IGNACIO-LATORRE"
REPO="tesis-drones-amba"
PRIVADO=true
DESCRIPCION="Trabajo Final de Maestria MiM+A (UTDT) - viabilidad economica del delivery con drones en el AMBA"

# --- verificaciones previas -------------------------------------------------

command -v git >/dev/null || { echo "Falta git."; exit 1; }
command -v curl >/dev/null || { echo "Falta curl."; exit 1; }

if [[ ! -f README.md || ! -d scripts ]]; then
  echo "Ejecutalo desde adentro de la carpeta del repo (la que tiene README.md y scripts/)."
  exit 1
fi

if [[ -f .env ]]; then
  echo "AVISO: hay un archivo .env en esta carpeta."
  grep -q '^\.env$' .gitignore || { echo "Y NO esta en .gitignore. Abortando."; exit 1; }
  echo "Esta en .gitignore, no se va a subir. Sigo."
fi

# --- token ------------------------------------------------------------------

# Orden: variable de entorno GITHUB_TOKEN, despues GITHUB_TOKEN en .env,
# y si no hay ninguna lo pide por entrada oculta.
TOKEN="${GITHUB_TOKEN:-}"
if [[ -z "$TOKEN" && -f .env ]]; then
  TOKEN=$(grep -E '^GITHUB_TOKEN=' .env | head -n1 | cut -d= -f2- | tr -d '"'"'"' \r')
fi
if [[ -z "$TOKEN" ]]; then
  read -rsp "Pega tu token de GitHub (no se va a ver): " TOKEN
  echo
fi
[[ -n "$TOKEN" ]] || { echo "Token vacio."; exit 1; }

LOGIN=$(curl -fsS -H "Authorization: Bearer $TOKEN" \
             -H "Accept: application/vnd.github+json" \
             https://api.github.com/user | grep -o '"login": *"[^"]*"' | cut -d'"' -f4)

[[ -n "$LOGIN" ]] || { echo "El token no autentica. Revisa que sea valido."; exit 1; }
echo "Autenticado como: $LOGIN"

# --- crear el repo ----------------------------------------------------------

echo "Creando $LOGIN/$REPO ..."
HTTP=$(curl -s -o /tmp/gh_resp.json -w '%{http_code}' \
  -X POST https://api.github.com/user/repos \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -d "{\"name\":\"$REPO\",\"description\":\"$DESCRIPCION\",\"private\":$PRIVADO,\"auto_init\":false}")

case "$HTTP" in
  201) echo "Repositorio creado." ;;
  422) echo "Ya existe un repo con ese nombre. Sigo con el push." ;;
  403) echo "El token no tiene permiso para crear repositorios."; cat /tmp/gh_resp.json; exit 1 ;;
  401) echo "Token invalido o expirado."; exit 1 ;;
  *)   echo "Respuesta inesperada (HTTP $HTTP):"; cat /tmp/gh_resp.json; exit 1 ;;
esac

# --- commit y push ----------------------------------------------------------

[[ -d .git ]] || git init -q
git add -A

if git diff --cached --quiet 2>/dev/null && git rev-parse HEAD >/dev/null 2>&1; then
  echo "No hay cambios para commitear."
else
  git commit -q -m "Estructura inicial: extraccion Wikimapia y procesamiento AMBA"
  echo "Commit hecho."
fi

git branch -M main
git remote remove origin 2>/dev/null || true
# El token va en la URL solo para este push; despues se limpia el remote.
git remote add origin "https://${LOGIN}:${TOKEN}@github.com/${LOGIN}/${REPO}.git"

echo "Subiendo..."
git push -u origin main -q

# Deja el remote sin credenciales incrustadas
git remote set-url origin "https://github.com/${LOGIN}/${REPO}.git"
unset TOKEN
rm -f /tmp/gh_resp.json

echo
echo "Listo: https://github.com/${LOGIN}/${REPO}"
echo
echo "Ultimo paso: si no vas a reusar el token, borralo en"
echo "https://github.com/settings/tokens"
