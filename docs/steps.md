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

La conexión GitHub de esta conversación rechazó la creación de una rama con
`403 Resource not accessible by integration`. No se ha publicado esta rama ni
ejecutado el workflow remoto. Se necesita acceso de escritura o el push desde tu equipo.

## Siguientes etapas

1. Implementar comunidades densas con un algoritmo y criterio documentados.
2. Añadir FastAPI con `/v1/graphs`, `/v1/jobs` y contratos de trabajo.
3. Añadir S3 y DynamoDB para que no exista un grafo global mutable en la API.
4. Añadir SQS, workers, reducción, idempotencia y recuperación de fallos.
5. Desplegar infraestructura AWS según cuenta y permisos, y automatizar su despliegue.
6. Medir escalabilidad, reunir informes de pruebas y preparar la demostración.

Antes de la fase AWS hay que saber si se usa AWS Academy/Learner Lab o una cuenta
propia. No hacen falta claves ni contraseñas pegadas en la conversación.
