# Arquitectura objetivo — Python

Estado: propuesta; el código actual implementa únicamente el motor local.

## Decisión

El usuario elige Python. Se conserva el historial Java en `public-clean` y se
construye la nueva versión en `refactor/python-distributed`. El núcleo no depende
del framework web ni de AWS, para poder probarlo y ejecutarlo en distintos workers.

La versión Java auditada (`b0f678a`) guardaba un solo grafo en memoria del servicio,
sin persistencia compartida. Las réplicas no podían consultar un estado común y
las operaciones sincronizadas podían bloquearse entre sí. Cambiar el lenguaje
no resuelve eso: se debe cambiar la arquitectura.

## Capas de aplicación y tecnología

| Aplicación objetivo | Tecnología propuesta | Estado |
|---|---|---|
| Motor de grafos | Python, biblioteca estándar | Implementado parcialmente |
| API de trabajos y consultas | FastAPI; servicio ECS objetivo | Adaptador HTTP local parcial |
| Workers de construcción y análisis | Procesos Python en otro servicio ECS | Pendiente |
| Reparto de trabajos y errores | SQS y DLQ | Pendiente |
| Diccionarios, particiones y resultados | S3 | Pendiente |
| Catálogo y estados de trabajos | DynamoDB | Pendiente |
| Acceso, imágenes y observabilidad | ALB, ECR, IAM y CloudWatch | Pendiente |

FastAPI ya forma parte del adaptador local; Boto3 se incorporará con los adaptadores
AWS. ECS/Fargate o ECS/EC2 se concretará según las restricciones de AWS Academy o de la
cuenta propia. La infraestructura deberá quedar declarada y probada, con su coste
y procedimiento de eliminación documentados. No hay recursos desplegados aquí.

La primera API usa una factoría de aplicación y el puerto `GraphRepository`. El
adaptador `InMemoryGraphRepository` está protegido para acceso concurrente dentro
de un proceso, pero no ofrece durabilidad ni estado compartido. Esta separación
permite reemplazarlo posteriormente sin acoplar FastAPI al SDK de AWS.

## Flujo distribuido propuesto

1. La API registra un trabajo con ID y devuelve HTTP 202.
2. Un mecanismo persistente de envío publica en SQS las particiones pendientes.
3. Varios workers consumen particiones y leen el diccionario versionado de S3.
4. Cada worker escribe su resultado y confirma su partición mediante una operación
   condicional. Los conjuntos Python se serializarán como listas ordenadas en JSON.
5. Cuando todas las particiones están confirmadas, un reductor publica el grafo.
6. Cualquier réplica de la API puede consultar el estado y el resultado compartidos.

Cada patrón tiene un único propietario para un número fijo de particiones. Ese
número, el algoritmo de asignación y la versión del diccionario forman parte del
trabajo y no pueden cambiar durante su ejecución.

## Fallos que hay que resolver antes de considerarlo distribuido

- SQS puede entregar un mensaje repetido: reclamar trabajo con arrendamiento y
  token de intento, renovar visibilidad y evitar que un worker antiguo confirme.
- Registrar en DynamoDB y enviar a SQS no es una transacción: usar una bandeja de
  salida o reconciliación persistente para recuperar trabajos no encolados.
- No contar una partición dos veces; el reductor solo utiliza resultados confirmados.
- Reintentos limitados, DLQ y estado de fallo visible para el cliente.
- Guardar objetos completos antes de confirmar éxito; aislar resultados por intento.

La idempotencia de la unión probada aquí es solo una propiedad del motor. No se
ha implementado todavía este protocolo de coordinación.

## Límites y demostración

La construcción se podrá distribuir por particiones. BFS y la reducción inicial
seguirán necesitando el grafo completo en un worker; se deberá medir su memoria.
El motor local ya limita estados explorados, profundidad y tiempo en las búsquedas
de todos los caminos y del camino simple más largo entre dos nodos. Devuelve
`complete`, `stop_reason` y `explored_states`; queda pendiente transportar ese
contrato a la API y decidir límites operativos. No se confunde el camino simple más
largo con el diámetro ni componentes con comunidades densas.

## Decisión sobre subgrafos densos

Se usa descomposición `k-core`. El `k-core` es el subgrafo inducido maximal en el
que cada nodo tiene grado interno igual o superior a `k`. Se calcula eliminando
repetidamente los nodos que no cumplen el umbral; no basta con filtrar una sola vez,
porque cada eliminación puede reducir el grado de sus vecinos.

Las regiones conexas del resultado se presentan como subgrafos densos. La elección
es determinista, no añade dependencias y ofrece un parámetro fácil de explicar. No
se etiqueta como detección de comunidades por modularidad: métodos como Louvain
responden a una definición diferente y podrían añadirse como estrategia futura.

En `data/words3.txt`, el `3-core` está formado por `bat`, `cat`, `mat` y `rat`; el
`4-core` está vacío. El coste del peeling es lineal en nodos y aristas para un grafo
representado mediante conjuntos de adyacencia.

Para demostrar el sistema final: ejecutar al menos dos workers con IDs distintos
procesando un mismo grafo, comparar el resultado con el oráculo local, recuperar una
caída, comprobar entregas repetidas y medir uno frente a varios workers. Añadir vistas
de aplicación/tecnología en ArchiMate y decisiones y transición bajo el marco TOGAF.
