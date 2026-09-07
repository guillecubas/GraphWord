# Construcción por particiones en procesos locales

`POST /v1/jobs/partitioned-builds` en `graphword.local_app` recibe `words` y
`partitions` (1–64). Registra en una transacción SQLite N trabajos
`BUILD_PARTITION`, un trabajo `REDUCE_GRAPH` y sus dependencias. Devuelve 202 y
`Location: /v1/jobs/{id}` para consultar el reductor. La aplicación en memoria
`graphword.api:app` devuelve 503 para este endpoint: carece de este coordinador.
El endpoint anterior `graph-builds` conserva su construcción en un solo worker.

Cada partición procesa únicamente sus patrones SHA-256, aunque recorre el
diccionario completo. El número de particiones queda fijado al registrar el flujo.
El reductor permanece PENDING, sin consumir intentos, hasta que todas las
dependencias están SUCCEEDED. Entonces une exclusivamente los grafos referenciados
por resultados confirmados. Su resultado contiene `graph_id`, como en el contrato
anterior. Cada partición guarda además `worker_id` y su índice en el resultado.

Un error reintentable vuelve a poner la partición en PENDING. Un fallo definitivo
marca el reductor FAILED; el siguiente sondeo de workers también propaga el fallo
si se agotan los intentos al recuperar un lease vencido. Las otras particiones
pueden terminar: todavía no hay cancelación del trabajo sobrante.

## Ejecutar en PowerShell

Desde la carpeta del repositorio, abrir tres terminales con el mismo directorio.
La base predeterminada es `var/graphword.db`:

```powershell
# Terminal 1: API
.\.venv\Scripts\python.exe -m uvicorn graphword.local_app:app

# Terminal 2: worker A
.\.venv\Scripts\python.exe -m graphword.worker_cli --worker-id worker-a

# Terminal 3: worker B
.\.venv\Scripts\python.exe -m graphword.worker_cli --worker-id worker-b
```

En otra terminal:

```powershell
$build = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/v1/jobs/partitioned-builds' -ContentType 'application/json' -Body '{"words":["cat","bat","bad","dad","dog"],"partitions":4}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/jobs/$($build.job_id)"
```

El reparto competitivo no garantiza que ambos workers obtengan trabajo con un
diccionario pequeño. La prueba `test_http_build_reduced_after_two_worker_processes`
asigna una ejecución `--once` a cada proceso para demostrar colaboración de forma
reproducible; no mide aceleración ni solapamiento temporal.

## Garantías y límites

SQLite serializa las reclamaciones; los tokens y leases impiden que un intento
antiguo publique un resultado confirmado. La escritura del grafo y la confirmación
siguen siendo transacciones distintas: pueden quedar grafos huérfanos. No se afirma
ejecución exactamente una vez ni idempotencia de peticiones HTTP repetidas.

El reductor carga todas las particiones en memoria. Hay duplicación del diccionario
en los trabajos y de nodos en las particiones. No hay renovación de lease: trabajos
que excedan su duración necesitan un lease mayor o la futura renovación automática.
El fichero SQLite debe estar en un disco local de la misma máquina. AWS, SQS,
outbox/reconciliación entre servicios, limpieza de huérfanos y medidas de rendimiento
siguen pendientes.
