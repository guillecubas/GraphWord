# Paso a paso

## Lo que se entrega ahora

1. `chore: replace Java scaffold with Python project and CI`: cambia la estructura,
   elimina la implementación Java en esta rama y configura las pruebas de Python.
2. `feat: add partitionable Python graph engine and twelve tests`: implementa el
   núcleo y la demostración, verificando las conexiones con un oráculo por pares.
3. `docs: explain Python migration and verified local usage`: explica el código,
   registra evidencia local y marca qué falta para la entrega final.
4. `feat: add bounded exhaustive path searches`: añade todos los caminos simples y
   el camino simple más largo entre dos nodos con límites y estado de completitud.
5. `docs: document bounded path search semantics`: documenta qué garantiza el
   resultado exacto y cómo debe interpretarse una búsqueda truncada.
6. `feat: identify dense subgraphs with k-cores`: implementa un criterio explícito
   de densidad interna sin confundirlo con componentes conexas.
7. `docs: explain the k-core density criterion`: registra la decisión, sus límites
   y un resultado reproducible con el diccionario de ejemplo.
8. `feat: add versioned local FastAPI adapter`: añade creación, resumen y camino
   mínimo por HTTP, un puerto de almacenamiento y cinco pruebas de contrato.
9. `docs: describe the first local HTTP milestone`: documenta ejecución, endpoints
   y las limitaciones explícitas del repositorio en memoria.
10. `feat: expose bounded graph queries over HTTP`: completa la superficie HTTP del
    motor con grados, caminos acotados y subgrafos densos.
11. `docs: document complete synchronous API contracts`: registra límites,
    completitud y semántica de las ocho rutas actuales.

La rama anterior de migración Java no es un requisito. Este cambio parte de
`public-clean` en `b0f678a`. El parche Python reemplaza al parche Java de la conversación.

## Probar el ZIP

Extraer el ZIP y abrir una terminal dentro de `GraphWord-python`:

```bash
python -m unittest discover -s tests -v
python -m graphword data/words3.txt --partitions 4 --from cat --to dad
```

## Conservar los commits y subir a GitHub

El ZIP contiene también `GraphWord-python.patch`, situado junto a la carpeta del
código. Aplicarlo desde una copia limpia de tu repositorio original. Sustituir la
ruta del parche por la ruta de descarga real:

```bash
git switch public-clean
git pull --ff-only
git switch -c refactor/python-distributed
git am /ruta/GraphWord-python.patch
python -m unittest discover -s tests -v
git push -u origin refactor/python-distributed
```

`git am` crea los tres commits con sus mensajes. Si has cambiado los mismos archivos
en `public-clean`, puede haber conflictos: no usar `reset --hard`; revisar el conflicto
o cancelar solo la aplicación del parche con `git am --abort`.

El intento de la conversación anterior recibió un error 403, pero en este entorno
la rama `refactor/python-distributed` sí se publicó y GitHub Actions se ejecuta en
cada push. Los identificadores de las ejecuciones verificadas figuran en
`docs/validation.md`.

## Siguientes etapas

1. Definir la máquina de estados de trabajos y convertir construcción y búsquedas
   costosas en operaciones asíncronas con contratos 202.
2. Añadir S3 y DynamoDB para que no exista un grafo global mutable en la API.
3. Añadir SQS, workers, reducción, idempotencia y recuperación de fallos.
4. Desplegar infraestructura AWS según cuenta y permisos, y automatizar su despliegue.
5. Medir escalabilidad, reunir informes de pruebas y preparar la demostración.

Antes de la fase AWS hay que saber si se usa AWS Academy/Learner Lab o una cuenta
propia. No hacen falta claves ni contraseñas pegadas en la conversación.
