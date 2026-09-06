# GraphWord en Python

Reimplementación con motor de grafos particionable, API HTTP local y pruebas. Esta
rama sustituye Java por Python. No contiene todavía integración con AWS ni un
despliegue distribuido.

## Ejecutar

Python 3.11 o superior. Crear un entorno e instalar el proyecto:

```bash
python -m venv .venv
python -m pip install -e ".[test]"
python -m unittest discover -s tests -v
python -m graphword data/words3.txt --partitions 4 --from cat --to dad
```

En Windows puedes sustituir `python` por `py -3.12` si ese es tu comando instalado.
El ejemplo devuelve 20 nodos, 29 aristas, 2 componentes y el camino
`cat → bat → bad → dad`. Las cuatro particiones se ejecutan secuencialmente en local.

## Qué hace cada archivo

| Archivo | Responsabilidad |
|---|---|
| `graphword/graph.py` | Normalización, constructor por patrones, unión, BFS, componentes y grados |
| `graphword/api.py` | Contratos HTTP versionados y factoría FastAPI |
| `graphword/storage.py` | Puerto de persistencia y adaptador local en memoria |
| `graphword/__main__.py` | Demostración por terminal; lectura del fichero y salida JSON |
| `tests/test_graph.py` | 12 pruebas, incluyendo comparación con un constructor independiente |
| `.github/workflows/ci.yml` | Pruebas en Python 3.11/3.12 y conservación de sus resultados |
| `docs/architecture.md` | Diseño objetivo de aplicación y tecnología, y limitaciones |
| `docs/steps.md` | Guía de commits y siguientes etapas |

## Cómo se forman las particiones

`cat` produce los patrones `*at`, `c*t`, `ca*`. Dos palabras que comparten un patrón
se conectan. SHA-256 asigna cada patrón completo a una partición de forma estable:
`int.from_bytes(sha256(pattern.encode('ascii')).digest(), 'big') % partitions`.
No usamos `hash()` de Python porque su valor para cadenas puede variar entre procesos.

Así no se pierde una conexión entre palabras que una división por bloques hubiera
separado. La unión conserva nodos aislados y tolera que se repita una partición.
Esta propiedad no equivale todavía a implementar reintentos seguros de trabajos AWS.

El código crea cadenas de patrones y las procesa para cada palabra: el trabajo de
indexación incluye O(N L²), además del coste de emitir aristas. Cada partición vuelve
a recorrer el diccionario. No se afirma una mejora de rendimiento sin medirla.

## Estado funcional

Implementado: construcción, camino mínimo, todos los caminos simples entre dos
nodos, mejor camino simple largo encontrado entre dos nodos, componentes conexas,
nodos aislados, selección por grado, nodos de grado máximo y subgrafos densos
mediante `k-core`.

Las dos búsquedas combinatorias aceptan límites de estados, profundidad y tiempo;
la enumeración acepta además un máximo de resultados. Devuelven `complete`,
`stop_reason` y `explored_states`. Un camino largo con `complete=false` es solo el
mejor encontrado: no se presenta como máximo garantizado.

`dense_subgraphs(graph, minimum_degree=k)` devuelve las regiones conexas del
`k-core`: dentro del subgrafo resultante, cada nodo tiene al menos `k` vecinos.
Es un criterio estructural reproducible, no una partición por modularidad como
Louvain. Componentes conexas y subgrafos densos siguen siendo conceptos distintos.

Pendiente: convertir construcción y consultas costosas en trabajos asíncronos,
añadir persistencia compartida, workers, infraestructura y demostración AWS.

## API local

Arrancar con `uvicorn graphword.api:app --reload`. La documentación interactiva
queda en `http://127.0.0.1:8000/docs`. La versión local permite crear un grafo y
consultar resumen, grados, aislados, caminos y subgrafos `k-core`:

```bash
curl -X POST http://127.0.0.1:8000/v1/graphs \
  -H "Content-Type: application/json" \
  -d '{"words":["cat","bat","bad","dad"],"partitions":2}'
```

El repositorio actual vive en memoria dentro de un único proceso. Reiniciar la API
borra los grafos y dos réplicas no comparten datos. Esta limitación es intencionada
y está aislada tras `GraphRepository`; no constituye todavía arquitectura distribuida.

Los archivos `data/` proceden del repositorio original y se conservan como ejemplos.
Sus fuentes y licencias deben documentarse antes de presentarlos como un corpus real.
El filtro acepta letras ASCII tras normalizar; no verifica significado ni pronunciación.

## Docker opcional

```bash
docker build -t graphword-python .
docker run --rm graphword-python
```

El contenedor expone la API en el puerto 8000. El Dockerfile se actualizó, pero la
construcción local no pudo verificarse porque Docker Desktop no estaba iniciado.

Referencias: [unittest](https://docs.python.org/3/library/unittest.html),
[hashlib](https://docs.python.org/3/library/hashlib.html).
