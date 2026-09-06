# Contrato HTTP local

Estado: implementado y probado localmente; no desplegado.

| Método y ruta | Resultado | Estado normal |
|---|---|---|
| `GET /health` | Salud y tipo de almacenamiento | 200 |
| `POST /v1/graphs` | Crea el grafo síncronamente | 201 |
| `GET /v1/graphs/{graph_id}` | Recupera su resumen | 200 |
| `POST /v1/graphs/{graph_id}/queries/shortest-path` | Camino mínimo o lista vacía | 200 |
| `POST /v1/graphs/{graph_id}/queries/all-simple-paths` | Caminos simples y completitud | 200 |
| `POST /v1/graphs/{graph_id}/queries/longest-simple-path` | Mejor camino largo y optimalidad | 200 |
| `GET /v1/graphs/{graph_id}/nodes?degree=N` | Nodos con grado exacto `N` | 200 |
| `GET /v1/graphs/{graph_id}/dense-subgraphs?minimum_degree=K` | Regiones del `k-core` | 200 |

La creación recibe `words` y entre 1 y 64 particiones. Devuelve un UUID, cabecera
`Location`, número de nodos y aristas, componentes, aislados y grados máximos.
Las palabras se normalizan mediante las mismas reglas del motor.

Un UUID inexistente devuelve 404 con `code=graph_not_found`. Una palabra que no
pertenece al grafo devuelve 422 con `code=unknown_word`; una lista sin palabras
válidas devuelve 422 con `code=empty_dictionary`. Las infracciones estructurales
del modelo también devuelven 422 mediante la validación estándar de FastAPI.

Las búsquedas combinatorias admiten `max_states` hasta 1 000 000, `max_depth`
hasta 10 000 y `timeout_seconds` hasta 30. La enumeración admite además `max_paths`
hasta 10 000. Los valores predeterminados son límites de seguridad, no garantías de
que el problema finalice: siempre deben interpretarse `complete`, `stop_reason` y
`explored_states`. En el camino largo, `complete=false` significa que se devuelve
el mejor candidato encontrado, no un máximo demostrado.

Los aislados se consultan con `degree=0`. Los nodos de grado máximo ya figuran en el
resumen del grafo. `dense-subgraphs` usa `k-core`; no afirma aplicar Louvain ni otra
partición por modularidad.

La creación es síncrona y el almacenamiento es local al proceso. La API todavía no
devuelve 202 ni crea trabajos porque aún no existen una cola y una máquina de estados
persistente que permitan sostener ese contrato correctamente.
