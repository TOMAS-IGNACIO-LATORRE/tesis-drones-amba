# CACE — Estudios Anuales de Comercio Electrónico, serie 2015-2025

Cifras públicas de los Estudios Anuales de la Cámara Argentina de Comercio
Electrónico (cace.org.ar). Cada año CACE publica un resumen en PDF de acceso
libre en <https://cace.org.ar/pages/biblioteca-de-estudios> (el informe completo
es para socios); esos PDF están en `data/raw/cace/` (no versionados) y en
Drive, `06_mercado_ecommerce/crudo/estudios_anuales_pdf/`.

`scripts/build_cace_serie.py` tiene las cifras transcriptas de cada PDF y
genera:

- `cace_estudio_anual_serie_2015_2025.csv`: formato largo, una fila por
  indicador y año, con unidad, detalle y la URL del PDF de donde sale cada
  valor.
- `cace_estudio_anual_serie_2015_2025_ancha.csv`: una fila por año, los
  indicadores en columnas.

Indicadores: facturación (millones de pesos corrientes), variación
interanual, inflación INDEC citada por CACE, órdenes de compra, unidades,
ticket promedio, compradores totales y nuevos, participación de AMBA y demás
regiones en la facturación, logística (envío a domicilio vs retiro, entregas
hasta 24 h, y plazos en AMBA vs interior 2019-2025), medios de pago.

Cuidados al usar la serie:

- Los pesos son corrientes: para comparar años hay que deflactar con el IPC
  de INDEC (o convertir a dólares). Entre 2019 y 2024 la facturación creció
  siempre por encima de la inflación que cita el propio informe.
- Metodología: encuesta online a compradores de 18 a 65 años (fase demanda,
  ~1.100 casos) y encuesta a empresas socias (fase oferta, 200 a 290
  respuestas según el año). El trabajo de campo lo hizo Kantar (Kantar TNS en
  2016-2018, Kantar Insights después); citarlo como "CACE/Kantar".
- AMBA cambió de definición en 2023: hasta 2022 el resto de la provincia
  de Buenos Aires iba dentro de "Centro"; desde 2023 AMBA = CABA + GBA y el
  resto de la provincia se reporta aparte. Ojo con 2025: AMBA sube de 42 % a
  52 % mientras el resto de la provincia cae de 17 % a 5 %, y la suma de las
  dos casi no se mueve (59 % a 57 %). Parece reasignación entre categorías,
  no un cambio real; usar la suma AMBA + provincia como cantidad estable.
- El ticket promedio de 2024 ($92.341) no cierra con la facturación y las
  órdenes del mismo informe (22.025.462 / 246 = $89.535). Es una
  inconsistencia de CACE; todos los demás años reproducen el cociente.
- Los porcentajes de logística son sobre ventas declaradas por las empresas
  (no incluyen marketplaces ni turismo); las preferencias de entrega son
  respuesta múltiple de los compradores.
- Valores redondeados en los informes anuales (1.520.000 / 2.846.000 /
  7.829.000) se reemplazaron por los de la serie retrospectiva del informe
  2024 (1.520.640 / 2.846.154 / 7.829.835). Los nuevos compradores de 2024
  figuran como 536.632 y 536.642 en distintas láminas del mismo informe.

Uso en la tesis: penetración (compradores sobre población), ticket promedio,
participación del AMBA, frecuencia de compra y share de entregas en el día
en AMBA, como calibración de la demanda sintética. Licencia: uso público con
cita. Consultado el 2026-09-08 y 2026-09-09.
