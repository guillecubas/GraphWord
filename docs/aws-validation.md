# Informe de validación AWS

Fecha de ejecución: 2 de octubre de 2026. Cuenta: AWS Academy Learner Lab.
Región: `us-east-1`. Las credenciales no forman parte del código ni de este informe.

## Código y pruebas automáticas

58 pruebas pasan localmente con Python 3.12.14, sin fallos ni errores.
Incluyen las 43 de etapas anteriores, 11 de adaptadores AWS con Moto y 4 de despliegue.

Casos nuevos: lectura/escritura S3, error de grafo inexistente, construcción por
particiones, equivalencia del grafo completo, API con repositorios compartidos,
indisponibilidad de SQS, duplicados, expiración, token antiguo, límite de reintentos,
propagación de fallo al padre, acuse SQS fallido después de confirmar, entradas vacías,
conflicto de revisiones y fallo simulado de transacción. Las pruebas de infraestructura
verifican permisos 0644 del paquete, empaquetado determinista con lista permitida,
dos instancias sin ingreso, IMDSv2, reemplazo por versión y retención de datos.

El fallo de transacción se inyecta antes de escribir: demuestra que el adaptador no
crea trabajos fuera de la llamada transaccional. La atomicidad del servicio real
la proporciona DynamoDB; no se afirma haber inyectado una transacción parcialmente
confirmada en AWS.

CI del código `cacb4ee`: [GitHub Actions 37013275740](https://github.com/guillecubas/GraphWord/actions/runs/37013275740),
resultado `success`. La matriz utiliza Python 3.11 y 3.12. Moto no demuestra permisos
reales del laboratorio, por lo que se comprueba también el despliegue remoto.

## Infraestructura realmente creada

- Stack `graphword-storage`: S3, DynamoDB, SQS, DLQ y grupo CloudWatch.
- Stack `graphword-compute`: dos EC2 `t3.micro`, discos cifrados y grupo de seguridad sin ingreso.
- Rol existente `LabInstanceProfile`; no se crearon ni copiaron claves en EC2.
- API en loopback, un reconciliador y dos workers, supervisados por systemd.
- Configuración e IDs exactos en `var/aws-deployment.json`, excluido de Git.

El despliegue no depende de Docker ni de ECS. Son dos máquinas con almacenamiento
compartido en servicios AWS, no réplicas que mantengan cada una un grafo en memoria.

## Incidencias detectadas durante la verificación

1. DynamoDB devuelve números `Decimal`: se convierten en valores JSON ordinarios
   en el adaptador; la prueba comprueba también los resultados de las particiones.
2. El terminal Windows no representaba algunos símbolos de systemd: se configuró UTF-8.
3. El ZIP determinista heredaba permisos demasiado restrictivos: se fijaron 0644 y
   se añadió una prueba. Los servicios siguen ejecutándose sin privilegios de root.
4. Un comando de estado podía ocultar un fallo de systemd al acabar con un comando
   correcto: ahora se comprueban explícitamente los servicios activos y el código de salida.

Las actualizaciones reemplazaron los nodos de la aplicación y sus discos, manteniendo
la tabla y el bucket. Las versiones antiguas de código siguen en el prefijo `releases/`.

## Evidencia remota

Los scripts conservan `var/aws-status.json`, `var/aws-smoke.json` y el identificador
del comando SSM. La prueba final terminó con `Success` y código de salida cero.

- Comando SSM: `52f888fc-0260-4991-be93-82e602ec532e`.
- Trabajo padre: `c243e4cb-ceca-40ea-887f-d5dbfab78be6`.
- Grafo: `1f0aac40-e03f-4259-a1db-aa4c899a209d`.
- Registro: 13:32:35 UTC; éxito confirmado: 13:33:23 UTC.
- Entrada: `cat`, `bat`, `bad`, `dad`, `mat`, `rat`, `zzz`; ocho particiones.
- Resultado: 7 nodos, 8 aristas, 2 componentes, aislado `zzz`, grado máximo 4 en `bat`.
- Camino mínimo por HTTP: `cat → bat → bad → dad`.
- `oracle_equal=true`: igualdad de toda la adyacencia, no solo del resumen.
- `two_workers_observed=true`: participación confirmada de ambas máquinas.

| Worker | Particiones confirmadas |
|---|---|
| `ip-172-31-82-83.ec2.internal` | 0, 1, 2, 3, 6 |
| `ip-172-31-94-41.ec2.internal` | 4, 5, 7 |

API y workers ejecutaban Python 3.11 sobre Amazon Linux. La versión de fuentes
desplegada está en el artefacto S3 con SHA-256
`82d92c56ae55d63916713d394d242b6198d5397a126f2c3cd14b631a77974641`.
Se comprobaron todos los servicios activos mediante SSM antes de la prueba.
Las latencias incluyen reconciliación periódica y red: no son una medida de mejora
frente a un solo worker ni una prueba de ejecución simultánea de cada partición.

## Estado al terminar

Se detuvieron y comprobaron en estado `stopped` las dos instancias de GraphWord
después de la demostración. Los datos S3/DynamoDB y los discos se conservaron.
La API no está disponible mientras estén detenidas. Para reanudar:
`python scripts/aws_operations.py start`, esperar y comprobar `status`.
Los discos y almacenamiento conservados pueden seguir consumiendo crédito.

## Límites que no se presentan como resultados demostrados

- No hay benchmark de aceleración, carga sostenida ni escalado automático.
- Los fallos y duplicados se prueban con Moto; no se ha matado deliberadamente un
  worker remoto a mitad de una partición ni provocado una interrupción real de AWS.
- No hay renovación de leases, idempotencia HTTP o recolección de objetos huérfanos.
- No hay alta disponibilidad de API/reconciliador, ni autenticación para acceso público.
- No se ha verificado Docker ni una configuración LocalStack en esta etapa.
- CI automática sí; despliegue manual reproducible sí; CD automático desde GitHub no.
- Las consultas siguen siendo síncronas en la API; lo repartido es la construcción.
- El corpus externo y su licencia, un modelo empresarial formal y medidas de
  rendimiento son tareas académicas adicionales, no capacidades inferidas de esta demo.
