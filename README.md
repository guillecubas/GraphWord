# GraphWord

Grafos de palabras: cada palabra es un nodo y dos palabras se conectan si difieren
en una letra. Incluye una API FastAPI, workers y almacenamiento local o AWS.

## Instalar

Python 3.11 o 3.12. Desde la raíz del proyecto, en PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test,aws,aws-test]"
```

## Ejecutar la API

```powershell
.\.venv\Scripts\python.exe -m uvicorn graphword.api.local_app:app --reload
```

Abre [Swagger](http://127.0.0.1:8000/docs). En otra terminal, inicia el worker:

```powershell
.\.venv\Scripts\python.exe -m graphword.trabajos.worker_cli --database var/graphword.db --worker-id worker-1
```

API y worker comparten `var/graphword.db`.

## Probar

En Swagger, ejecuta `POST /v1/graphs` con:

```json
{"words": ["cat", "bat", "bad", "dad"], "partitions": 2}
```

Usa el `graph_id` devuelto para consultar caminos, grados y subgrafos.
Para probar los workers, usa `POST /v1/jobs/partitioned-builds` y consulta
`GET /v1/jobs/{job_id}` hasta que termine.

```powershell
# Pruebas automáticas
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Demostración sin servidor
.\.venv\Scripts\python.exe -m graphword data/words3.txt --partitions 4 --from cat --to dad
```

## AWS

La modalidad AWS usa S3, DynamoDB y SQS, con API y workers en EC2.
El despliegue está en `scripts/despliegue/deploy_aws.py` y las operaciones en
`scripts/operaciones/aws_operations.py`. Requiere una cuenta o laboratorio AWS
y puede consumir crédito. Nunca incluyas credenciales en el repositorio.

Las licencias de los diccionarios se conservan en `data/curated/licenses/`.
