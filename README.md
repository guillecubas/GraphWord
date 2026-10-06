# GraphWord

Grafos de palabras: cada palabra es un nodo y dos palabras se conectan si difieren
en una letra. Incluye una API FastAPI, workers y almacenamiento local o AWS.

## Instalar

Python 3.11 o 3.12. Desde la raíz del proyecto, en PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test,aws,aws-test,public]"
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

CI y CD están en `.github/workflows/ci.yml` dentro de este repositorio privado.
CI prueba Python 3.11 y 3.12. Con `ENABLE_LAB_CD=true`, un push a
`refactor/python-distributed` despliega después de aprobar las pruebas.
También puedes usar **Actions → GraphWord CI/CD → Run workflow → deploy**.
El runner EC2 utiliza `LabInstanceProfile`, sin Secrets con claves AWS.
CD comprueba la aplicación y apaga API y worker; el runner se detiene aparte.
Deja `ENABLE_LAB_CD=false` cuando no uses el laboratorio. No hagas público el
repositorio mientras tenga conectado un runner con acceso a AWS.

Para acceder desde otro ordenador sin túnel, **GraphWord Public HTTPS** publica
la misma API en Lambda con HTTPS y contraseña (`GRAPHWORD_DEMO_PASSWORD`,
Repository secret, mínimo 16 caracteres; usuario `graphword`). El workflow
permite `deploy` o `pause` y no cambia las EC2. Con `ENABLE_PUBLIC_API=true`,
el CD principal también actualiza Lambda. Los trabajos asíncronos requieren
workers EC2 encendidos. La URL consume crédito por uso: páusala al terminar.

Las licencias de los diccionarios se conservan en `data/curated/licenses/`.
