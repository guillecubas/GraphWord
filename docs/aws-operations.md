# Cómo usar, demostrar y apagar GraphWord en AWS

Todos los comandos se ejecutan desde la carpeta `GraphWord-work`, en PowerShell.
Usamos `default` en `us-east-1`. No se necesitan claves dentro del proyecto.

## 1. Comprobar credenciales e instalar dependencias

```powershell
aws sts get-caller-identity --profile default --region us-east-1
.\.venv\Scripts\python.exe -m pip install -e ".[test,aws,aws-test]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Si la sesión caducó, actualiza los tres valores del perfil local desde AWS Academy.
No vuelvas a publicar claves. Dentro de EC2 se usa el rol de la máquina, no `default`.

## 2. Desplegar desde cero o publicar una nueva versión

```powershell
.\.venv\Scripts\python.exe scripts/deploy_aws.py --profile default
```

El script comprueba cuenta, red por defecto, imagen Amazon Linux y rol. Después crea
o actualiza `graphword-storage` y `graphword-compute`. No crea roles IAM. Si el
laboratorio deniega permisos o no tiene red por defecto, hay que revisar la causa;
no sustituir permisos por claves dentro del código ni abrir puertos indiscriminadamente.

Recursos: bucket privado S3, tabla DynamoDB bajo demanda, SQS, DLQ, grupo de logs
y dos EC2 `t3.micro` con discos cifrados de 8 GB. No se crea NAT ni balanceador.
Esto consume crédito de laboratorio. El saldo y restricciones de Academy deben
comprobarse en el portal; no hay una promesa de gratuidad ilimitada ni alarma de saldo.

El paquete incluye únicamente fuentes permitidas, configuración no secreta y
scripts. Excluye `.aws`, `.env`, `.venv` y `.git`. Su SHA-256 identifica la versión.
Para nuevas versiones se reemplazan los nodos; `cloud-init` no reinstala una versión
nueva por el mero hecho de reiniciar una máquina. Los datos permanecen en S3/DynamoDB.
Es un despliegue manual reproducible, no CD automático ni actualización sin interrupción.

El resultado queda en `var/aws-deployment.json`, excluido de Git. Contiene nombres
de recursos e IDs, no claves. No lo edites a mano: las operaciones verifican la cuenta
y las etiquetas de CloudFormation antes de actuar sobre las máquinas.

## 3. Esperar a que la aplicación esté lista

```powershell
.\.venv\Scripts\python.exe scripts/aws_operations.py status
```

La creación de EC2 no significa que Python y los servicios hayan terminado de
instalarse. Espera unos minutos y repite si SSM aún no registra la máquina.
Debes ver `cloud-init: done` y servicios `active (running)`.

## 4. Demostración automática real

```powershell
.\.venv\Scripts\python.exe scripts/aws_operations.py smoke
```

La prueba ejecuta llamadas HTTP dentro del nodo API, envía siete palabras y ocho
particiones, espera el reductor, compara TODAS las aristas con el motor local y
consulta un camino mínimo. Conserva resultado en `var/aws-smoke.json` y envía la
salida del comando remoto al grupo CloudWatch de la aplicación.

`oracle_equal=true` comprueba corrección. `two_workers_observed=true` comprueba que
al menos dos IDs distintos participaron. Este segundo dato debe revisarse: SQS
no garantiza repartir uniformemente un ejemplo pequeño. No es un benchmark de velocidad.

## 5. Abrir Swagger en tu navegador

Necesitas AWS CLI y el [complemento oficial Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
instalados en tu PC. El complemento no se instala automáticamente con este proyecto.

Primero muestra el comando exacto para tu nodo:

```powershell
.\.venv\Scripts\python.exe scripts/aws_operations.py tunnel-command
```

Copia y ejecuta el comando que imprime. Mantén esa terminal abierta. Después abre
`http://127.0.0.1:8000/docs`. Aunque la dirección parezca local, el túnel lleva
las peticiones a la API en AWS. No estás ejecutando la API en tu ordenador.
Si ya hay otra API local en el puerto 8000, cambia `localPortNumber` a 8001 y
abre `http://127.0.0.1:8001/docs`.

En Swagger:

1. Abre `POST /v1/jobs/partitioned-builds` y pulsa **Try it out**.
2. Envía `{"words":["cat","bat","bad","dad","mat","rat","zzz"],"partitions":8}`.
3. Copia `job_id`, consulta `GET /v1/jobs/{job_id}` hasta `SUCCEEDED`.
4. Copia `result.graph_id`, consulta el resumen y el camino de `cat` a `dad`.
5. Comprueba los aislados y `dense-subgraphs` con `minimum_degree=3`.

No existe una URL pública ni autenticación HTTP propia. SSM limita el acceso a
usuarios autorizados por IAM. No abras el puerto 8000 a todo Internet para evitar el túnel.

## 6. API y workers en tu PC usando los servicios AWS

También puedes mantener los procesos locales mientras S3/DynamoDB/SQS están en AWS:

```powershell
$config = Get-Content var/aws-deployment.json | ConvertFrom-Json
$env:AWS_PROFILE = 'default'
$env:AWS_DEFAULT_REGION = 'us-east-1'
$env:GRAPHWORD_BUCKET = $config.Bucket
$env:GRAPHWORD_TABLE = $config.Table
$env:GRAPHWORD_QUEUE_URL = $config.QueueUrl
.\.venv\Scripts\python.exe -m uvicorn graphword.aws_app:app --port 8000
```

En otras terminales, con las mismas variables, puedes ejecutar:

```powershell
.\.venv\Scripts\python.exe -m graphword.aws_worker worker --worker-id pc-worker
.\.venv\Scripts\python.exe -m graphword.aws_worker reconcile
```

Estos procesos consumirán la misma cola que EC2. No los arranques mientras intentas
medir exclusivamente los workers remotos. `GRAPHWORD_AWS_ENDPOINT` queda sin definir
para AWS real; solo se utiliza para una configuración explícita de LocalStack.

## 7. Detener y reanudar sin borrar datos

```powershell
.\.venv\Scripts\python.exe scripts/aws_operations.py stop
.\.venv\Scripts\python.exe scripts/aws_operations.py start
```

Son acciones alternativas: ejecuta `stop` al terminar y `start` cuando vayas a usarlo.
Esperar unos minutos tras `start` y volver a comprobar `status`. systemd arranca
automáticamente los servicios. Si un lease caducó, el reconciliador recupera el trabajo.

Detener reduce el consumo de cómputo, pero no elimina el coste de discos y almacenamiento.
Véase [la explicación oficial de AWS sobre instancias detenidas](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/how-ec2-instance-stop-start-works.html).
Cerrar el navegador o la terminal NO equivale a detener EC2. La duración de la sesión
Academy tampoco sustituye el control del saldo y de los recursos.

## 8. Eliminar definitivamente (solo cuando ya no necesites la demostración)

Antes, conserva `var/aws-deployment.json`, exporta resultados importantes y comprueba
los nombres exactos en la consola de CloudFormation. No borres el stack del laboratorio.

```powershell
aws cloudformation delete-stack --stack-name graphword-compute --profile default --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name graphword-compute --profile default --region us-east-1
aws cloudformation delete-stack --stack-name graphword-storage --profile default --region us-east-1
```

Esto elimina EC2 y sus discos; la pila de almacenamiento elimina colas y logs, pero
S3 y DynamoDB están marcados **Retain** para no perder resultados accidentalmente.
Por tanto, eliminar las pilas NO elimina todo el almacenamiento ni todo el coste.
Para una limpieza completa: identifica en el JSON el bucket y la tabla exactos,
exporta lo necesario y elimínalos expresamente desde sus consolas. Vaciar el bucket
y borrar la tabla es irreversible sin copia. No damos un borrado recursivo genérico
que pueda afectar a datos de otro proyecto.

## 9. Problemas comunes

| Síntoma | Qué revisar |
|---|---|
| `ExpiredToken` | Renovar los tres valores de la sesión del laboratorio |
| Perfil no encontrado | Ejecutar con el usuario/terminal donde se configuró `default` |
| `AccessDenied` | Servicio, acción y recurso denegados; límites del laboratorio |
| `InvalidInstanceId` en SSM | Nodo arrancado, rol, red y agente SSM; esperar instalación |
| Trabajo `PENDING` | Reconciliador activo, SQS accesible, workers arrancados |
| Trabajo `FAILED` | Leer `error`, intentos y logs; no reenviar sin entender la causa |
| API no responde al túnel | Nodo activo, servicio API, plugin SSM y puerto local libre |

Estado remoto y evidencia: [aws-validation.md](aws-validation.md).

Para revisar logs de ambos nodos: `python scripts/aws_operations.py logs`.
