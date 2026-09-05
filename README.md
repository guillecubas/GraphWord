# GraphWord en Python

Primera etapa de la reimplementación: motor de grafos particionable, demostración
local y pruebas. Esta rama sustituye Java por Python. No contiene todavía una API
HTTP, integración con AWS ni un despliegue distribuido.

## Ejecutar

Python 3.11 o superior. Esta etapa solo utiliza la biblioteca estándar: no requiere
instalar dependencias. Desde la carpeta del proyecto:

```bash
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

Implementado: construcción, camino mínimo, componentes conexas, nodos aislados,
selección por grado y nodos de grado máximo.

Pendiente: todos los caminos con límites explícitos, camino simple más largo con
estado de completitud, comunidades densas, API de trabajos, persistencia, workers,
infraestructura y demostración AWS. Componentes conexas no son comunidades densas.

Los archivos `data/` proceden del repositorio original y se conservan como ejemplos.
Sus fuentes y licencias deben documentarse antes de presentarlos como un corpus real.
El filtro acepta letras ASCII tras normalizar; no verifica significado ni pronunciación.

## Docker opcional

```bash
docker build -t graphword-python .
docker run --rm graphword-python
```

El contenedor ejecuta la misma demostración local; no expone un servidor HTTP.
Su construcción no se ha verificado en el entorno de esta entrega.

Referencias: [unittest](https://docs.python.org/3/library/unittest.html),
[hashlib](https://docs.python.org/3/library/hashlib.html).
