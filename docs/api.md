# Contrato HTTP local

Estado: implementado y probado localmente; no desplegado.

| Método y ruta | Resultado | Estado normal |
|---|---|---|
| `GET /health` | Salud y tipo de almacenamiento | 200 |
| `POST /v1/graphs` | Crea el grafo síncronamente | 201 |
| `GET /v1/graphs/{graph_id}` | Recupera su resumen | 200 |
| `POST /v1/graphs/{graph_id}/queries/shortest-path` | Camino mínimo o lista vacía | 200 |

La creación recibe `words` y entre 1 y 64 particiones. Devuelve un UUID, cabecera
`Location`, número de nodos y aristas, componentes, aislados y grados máximos.
Las palabras se normalizan mediante las mismas reglas del motor.

Un UUID inexistente devuelve 404 con `code=graph_not_found`. Una palabra que no
pertenece al grafo devuelve 422 con `code=unknown_word`; una lista sin palabras
válidas devuelve 422 con `code=empty_dictionary`. Las infracciones estructurales
del modelo también devuelven 422 mediante la validación estándar de FastAPI.

La creación es síncrona y el almacenamiento es local al proceso. La API todavía no
devuelve 202 ni crea trabajos porque aún no existen una cola y una máquina de estados
persistente que permitan sostener ese contrato correctamente.
