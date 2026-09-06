# Validación de esta etapa

Entorno local: Python 3.12.13.

Comando ejecutado: `python -m unittest discover -s tests -v`.
Resultado: 12 tests, 0 errores y 0 fallos.

Incluye 80 combinaciones de diccionario y número de particiones dentro de la prueba
de equivalencia (20 entradas generadas con semilla fija × 4 configuraciones). El
oráculo compara pares de palabras y no reutiliza el algoritmo por patrones.

Se comprobaron también duplicados, palabras aisladas, distintas longitudes,
normalización, camino mínimo, ausencia de camino, nodos desconocidos, grado,
componentes, entradas vacías, índices inválidos y estabilidad entre dos intérpretes
con distinta semilla de hash. La CLI se ejecuta en un subproceso durante las pruebas.

Demostración ejecutada:

```bash
python -m graphword data/words3.txt --partitions 4 --from cat --to dad
```

Resultado: 20 nodos, 29 aristas, 2 componentes; grado máximo 6 (`bat`);
camino `cat → bat → bad → dad`; ejecución `local-sequential`.

No verificado: ejecución en Python 3.11, construcción Docker, CI remoto,
API HTTP, comportamiento distribuido, despliegue AWS o rendimiento bajo carga.
El workflow está preparado para Python 3.11 y 3.12, pero configurarlo no prueba
que haya sido ejecutado en GitHub.

## Validación tras integrar el parche

Entorno local de Codex: Python 3.12.14 incluido en el runtime de la aplicación.

Se repitieron las 12 pruebas de la etapa inicial y la demostración, con el mismo
resultado. Después se añadieron 4 pruebas para enumeración completa, truncamiento
por cantidad y profundidad, camino simple más largo, límites y nodos desconocidos.
Resultado actual: 16 pruebas, 0 errores y 0 fallos. También se compilaron los módulos
con `py_compile` y `git diff --check` no detectó errores de whitespace.

La ejecución remota `33994842751` de GitHub Actions terminó correctamente para el
commit `eeaad2c`: pasaron los jobs de Python 3.11 y Python 3.12. Los enlaces y
artefactos de esa ejecución constituyen la evidencia de CI de esta etapa.

Sigue sin verificarse Docker, AWS, rendimiento bajo carga ni ejecución distribuida.

## Validación de subgrafos densos

Se añadieron dos pruebas: una comprueba el peeling recursivo y que el grafo original
no se modifica; la otra demuestra que las regiones del `k-core` no son simplemente
las componentes del grafo y valida parámetros erróneos. Resultado local acumulado:
18 pruebas, 0 errores y 0 fallos con Python 3.12.14.

Sobre `data/words3.txt`, el `3-core` contiene `bat`, `cat`, `mat` y `rat`, mientras
que el `4-core` está vacío. La ejecución `33995304808` de GitHub Actions validó el
hito completo en Python 3.11 y Python 3.12.

## Validación de la primera API

Se añadieron cinco pruebas HTTP para salud, creación y lectura de grafos, camino
mínimo, errores diferenciados y validación de entrada. Resultado local acumulado:
23 pruebas, 0 errores y 0 fallos con Python 3.12.14. El esquema OpenAPI contiene
cuatro rutas: `/health`, `/v1/graphs`, `/v1/graphs/{graph_id}` y la consulta
`shortest-path`.

También se arrancó Uvicorn realmente en `127.0.0.1:8765`: `/health` devolvió 200 y
la creación de un grafo de cuatro palabras devolvió 201 con 4 nodos, 3 aristas y
una componente. El proceso se detuvo al terminar la comprobación.

La construcción `docker build -t graphword-python-api:test .` se intentó y falló
antes de procesar el Dockerfile porque no estaba iniciado el motor Linux de Docker
Desktop (`dockerDesktopLinuxEngine`). Por tanto, el Dockerfile está preparado pero
la imagen no se considera verificada.

## Validación de las consultas HTTP completas

Se añadieron tres pruebas de contrato para enumeración truncada, camino largo sin
optimalidad demostrada, selección por grado, aislados y `k-core`; las validaciones
también cubren los máximos permitidos por la API. Resultado local acumulado:
26 pruebas, 0 errores y 0 fallos con Python 3.12.14.

El esquema OpenAPI 0.3.0 contiene ocho rutas. Esta validación prueba los contratos
HTTP síncronos y el adaptador local, no ejecución asíncrona ni distribuida.

## Validación de trabajos locales

Se añadieron siete pruebas: cinco del dominio de trabajos y el worker, y dos del
contrato HTTP. Cubren transición completa, recuperación de lease, rechazo de token
antiguo, reintentos agotados, publicación del grafo, respuesta 202 y error 404 de
trabajo. Resultado local acumulado: 33 pruebas, 0 errores y 0 fallos.

OpenAPI 0.4.0 contiene diez rutas. La prueba de extremo a extremo comparte los
repositorios en memoria entre API y worker; no demuestra comunicación entre procesos,
persistencia tras reinicio, SQS, DynamoDB ni AWS.
