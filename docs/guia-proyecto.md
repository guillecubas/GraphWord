# GraphWord explicado paso a paso

Guía para entender, ejecutar y defender el proyecto. Fecha: 2 de octubre de 2026.
Los resultados comprobados se recogen en [el informe AWS](aws-validation.md).

La integración se ha demostrado en AWS con dos workers de máquinas distintas:
ocho particiones producen el mismo grafo que el cálculo local. Pasan 58 pruebas
automáticas y la CI de Python 3.11 y 3.12. Esta guía explica las decisiones; los
comandos para repetir la demostración están en [aws-operations.md](aws-operations.md).

## 1. Qué estamos construyendo

GraphWord convierte palabras en un grafo. Una palabra es un nodo. Una conexión
une dos palabras de la misma longitud que cambian exactamente una letra.
Por ejemplo, `cat → bat → bad → dad` es un camino válido.

El objetivo es recibir peticiones por una API, repartir la construcción entre
trabajadores y conservar los resultados en un almacenamiento común. Así, los
procesos no dependen de la memoria de otro.

## 2. Por qué elegimos Python

**Qué hicimos:** separamos un motor de grafos escrito en Python del servidor web
y de los servicios AWS.

**Para qué:** comprobar los algoritmos sin necesitar una cuenta de AWS.

**Por qué:** Python permite explicar los algoritmos con diccionarios, conjuntos y
colas. Cambiar Java por Python no hace que una aplicación sea distribuida:
lo importante es separar responsabilidades y compartir el estado.

Archivos principales: `graphword/graph.py`, `storage.py`, `jobs.py` y `worker.py`.
Los repositorios son interfaces: el motor pide guardar o recuperar algo sin decidir
si se usa memoria, SQLite o AWS. Esto facilita las pruebas y cambiar de tecnología.

## 3. Preparar las palabras

**Qué:** quitar espacios, convertir a minúsculas, eliminar duplicados y aceptar
solo letras inglesas ASCII (`a` a `z`). Se conservan distintas longitudes, pero nunca
se conectan palabras de longitudes diferentes.

**Para qué:** que ` CAT ` y `cat` no se conviertan en dos nodos distintos.

**Por qué:** unas reglas explícitas hacen los resultados repetibles. El filtro no
sabe si una palabra existe en un diccionario: `zzz` sirve como ejemplo de aislado.
Los ficheros heredados de `data/` tienen procedencia/licencia pendiente de documentar;
no se presentan como un corpus autorizado. La demostración nueva usa una pequeña
lista escrita expresamente como ejemplo, no descarga diccionarios externos.

## 4. Construir conexiones y repartirlas

`cat` produce `*at`, `c*t` y `ca*`. `bat` comparte `*at`: por eso existe su conexión.

**Para qué:** agrupar candidatos que solo pueden diferir en una posición.

**Por qué:** los patrones permiten repartir el trabajo manteniendo juntas las
palabras que deben compararse. Dividir la lista en bloques puede perder la conexión
entre dos palabras situadas en bloques diferentes.

Cada patrón se asigna a una partición mediante SHA-256 y el resto de dividir por
el número de particiones. No usamos `hash()` de Python porque puede cambiar entre
procesos. SHA-256 aquí asigna trabajo; no cifra las palabras.

Cada partición sigue leyendo el diccionario completo. Repartir trabajo no garantiza
acelerarlo: hay costes de lectura, envío y combinación que debemos medir.

## 5. Resolver las consultas

| Pregunta | Solución | Por qué y límite |
|---|---|---|
| Camino mínimo | BFS, recorrido por niveles | Exacto en este grafo sin pesos |
| Todos los caminos simples | Exploración sin repetir nodos | Puede crecer muchísimo; tiene límites |
| Camino simple más largo | Mejor camino encontrado | Óptimo demostrado solo si `complete=true` |
| Mayor grado, grado elegido, aislados | Contar vecinos | Grado cero significa aislado |
| Subgrafos con grado interno mínimo | `k-core` | Criterio estructural explicable, no modularidad |

Un componente conexo agrupa nodos alcanzables, aunque tenga pocas conexiones.
Un `k-core` exige al menos `k` vecinos dentro del resultado, eliminando repetidamente
los nodos que no cumplen. No garantiza alta densidad relativa para cualquier tamaño,
ni equivale a una comunidad Louvain. Tampoco confundimos diámetro —máximo de caminos
mínimos— con el camino simple más largo.

Cuando una búsqueda se detiene por tiempo, profundidad, estados o resultados,
la respuesta indica `complete=false` y `stop_reason`. No ocultamos la truncación.

## 6. Crear la API con FastAPI

**Qué:** rutas HTTP para crear trabajos, consultar estados y consultar grafos.

**Para qué:** que un cliente use GraphWord sin importar las funciones Python.

**Por qué FastAPI:** valida los datos y genera documentación interactiva en `/docs`.
Los contratos están en [api.md](api.md).

Una construcción distribuida usa `POST /v1/jobs/partitioned-builds`. Devuelve
`202 Accepted`: está registrada, pero el resultado todavía no existe.
Después se consulta `GET /v1/jobs/{id}`. Cuando aparece `SUCCEEDED`, se obtiene
`result.graph_id` y se consulta el grafo.

`POST /v1/graphs` sigue siendo síncrono, útil para ejemplos pequeños; no demuestra
distribución. Las consultas actuales se resuelven en el proceso API; no hemos
distribuido una misma búsqueda de caminos entre workers.

## 7. Probar primero con memoria y SQLite

**Qué:** implementamos primero adaptadores sencillos sin servicios externos.

**Para qué:** encontrar fallos del motor y del contrato HTTP antes de añadir fallos
de red, permisos, credenciales y costes.

**Por qué SQLite:** permite a varios procesos de un ordenador compartir trabajos
y grafos de forma persistente. Es una etapa intermedia, no una base compartida entre
máquinas AWS. En el modo AWS no montamos ni compartimos ese archivo.

## 8. Elegir AWS Academy y credenciales temporales

**Qué:** usamos Learner Lab, perfil local `default` y región `us-east-1`.

**Para qué:** trabajar en la cuenta académica sin crear una cuenta personal.

**Por qué:** el laboratorio facilita permisos y crédito, pero tiene límites. No es
uso ilimitado ni una garantía de coste cero. El tiempo de sesión no equivale al saldo.
Las credenciales temporales necesitan access key, secret key y session token; cuando
caduquen hay que renovarlas localmente, nunca pegarlas en chats o GitHub.

En EC2 no copiamos esas claves: usamos el rol existente `LabInstanceProfile`.
El SDK recibe credenciales temporales de la máquina. El rol del laboratorio es
amplio; producción necesitaría roles de mínimo privilegio para cada componente.

## 9. Repartir responsabilidades en AWS

| Componente | Qué guarda o hace | Por qué lo elegimos |
|---|---|---|
| S3 | Diccionario y grafos JSON | Los archivos grandes no van en mensajes o filas |
| DynamoDB | Estado, dependencias, intentos y resultado confirmado | Escrituras condicionales para coordinar procesos |
| SQS | Identificadores de trabajos disponibles | Workers independientes consumen una cola común |
| DLQ | Mensajes con fallos reiterados de transporte | Permite investigarlos |
| Reconciliador | Revisa trabajos pendientes o caducados | Recupera envíos perdidos entre DynamoDB y SQS |
| EC2 + systemd | Ejecutan API y trabajadores | Configuración visible y compatible con Academy |
| SSM | Acceso administrativo y túnel a la API | Sin abrir puertos entrantes |
| CloudFormation | Declara recursos reproducibles | Evita depender de clics manuales |
| CloudWatch | Salida de comprobaciones remotas, retención 7 días | Evidencia operativa básica |

Los logs continuos de las aplicaciones están en `journalctl` de cada máquina.
No hay agente de envío continuo de todos esos logs ni alarmas configuradas todavía.

## 10. Recorrido de una construcción distribuida

```text
Cliente → API → entrada en S3 + trabajos en DynamoDB
                       ↓
               Reconciliador → SQS
                                 ↓
                       worker A / worker B
                                 ↓
                   particiones en S3 + confirmación
                                 ↓
                   reductor, cuando todas terminan
                                 ↓
                      grafo final en S3
                                 ↓
                    cliente consulta mediante API
```

Padre y particiones se registran juntos con una transacción de DynamoDB.
Para hasta 64 particiones son 65 registros, dentro del máximo de 100 acciones.
El diccionario se sube antes: si falla el registro puede quedar un objeto sin usar,
pero nunca se publica un trabajo que apunte a una entrada aún no escrita.

El reductor no suma un contador por mensaje recibido. Comprueba los IDs de las
particiones y solo utiliza resultados confirmados. Repetir un mensaje no
equivale a completar dos veces una partición.

## 11. Qué ocurre cuando algo falla

**Mensaje duplicado:** SQS puede repetir mensajes. DynamoDB permite que solo una
revisión válida reclame un trabajo pendiente. No afirmamos ejecución exactamente una vez.

**Worker caído:** la reserva temporal, llamada *lease*, vence. El reconciliador
devuelve el trabajo a pendientes si quedan intentos. Por defecto hay tres intentos.

**Worker antiguo que termina tarde:** su token ya no es válido o su reserva caducó;
no puede publicar éxito. Puede quedar un archivo huérfano en S3; no se usa como resultado.

**DynamoDB guarda, pero SQS falla:** el trabajo sigue pendiente. El reconciliador
intenta enviarlo en una pasada posterior, cada 30 segundos.

**S3 guarda, pero confirmar falla:** puede haber otro archivo en el siguiente intento.
Solo se lee el ID confirmado en DynamoDB. Aceptamos almacenamiento huérfano para
evitar sobrescribir resultados de otro intento; no hay recolector automático aún.

**Se agotan los intentos:** el trabajo pasa a `FAILED`; si era una partición, el
padre también falla en la siguiente reconciliación. No se cancelan automáticamente
las otras particiones. Los fallos de aplicación se consultan en DynamoDB/API;
la DLQ es para fallos reiterados de transporte, no una lista de todos los `FAILED`.

La reserva de los workers remotos es de 300 segundos, sin renovación automática.
Un trabajo que tarda más puede agotar intentos. Para grandes grafos habrá que
renovar leases y estudiar memoria. Las pruebas pequeñas no demuestran esa escala.
El reconciliador recorre la tabla completa: para muchos trabajos necesitaría
índices o una bandeja de salida especializada. Tampoco hay idempotencia HTTP:
repetir una petición de creación crea otro trabajo distinto.

## 12. Por qué dos EC2 y no ECS en esta entrega

La primera máquina aloja tres procesos: API, reconciliador y worker A.
La segunda aloja worker B. No comparten archivos locales; comparten S3, DynamoDB y SQS.
systemd reinicia procesos que fallan y permite revisar sus logs.

Elegimos EC2 para hacer visible la separación y usar el rol disponible en Academy.
ECS/Fargate sigue siendo una evolución posible, no un requisito para que workers de
máquinas diferentes cooperen. Esta elección evita ECR, balanceador y NAT Gateway.
Las instancias tienen IP pública para salir a AWS, pero su grupo de seguridad no
admite conexiones entrantes. Se exige IMDSv2 para obtener credenciales del rol.

La API escucha en `127.0.0.1` dentro de EC2. Un túnel SSM permite verla desde el
navegador. No es un servicio público autenticado, ni tiene alta disponibilidad:
API y reconciliador dependen del primer nodo. Detener las máquinas detiene el servicio.

## 13. Comprobar y publicar

**Pruebas del motor:** comparan particiones con un constructor independiente.
**Pruebas HTTP:** comprueban entradas, errores y respuestas.
**Pruebas AWS simuladas:** Moto reproduce servicios sin gastar crédito; comprobamos
duplicados, reintentos, caducidad, fallo de cola y confirmación tardía.
**Prueba AWS real:** usa la API de EC2, espera el resultado, comprueba los workers y
compara la adyacencia completa con el motor local. Véase el informe de resultados.

GitHub Actions ejecuta pruebas en Python 3.11 y 3.12 en cada push. Usa Moto y no
necesita claves AWS. El despliegue es un script manual reproducible: no hay despliegue
continuo automático desde GitHub con credenciales del laboratorio. Distinguimos
CI automática de despliegue manual. Los artefactos en S3 se identifican por SHA-256.

## 14. Perspectiva de arquitectura empresarial

En la capa de aplicación, el servicio ofrecido es construir y consultar grafos.
API, coordinador y workers realizan ese servicio; diccionarios, trabajos y grafos
son sus objetos de datos. En la capa tecnológica, EC2 ejecuta los componentes,
S3 conserva objetos, DynamoDB coordina y SQS comunica trabajo.

La transición seguida fue: motor comprobable → API → persistencia local →
particiones independientes → servicios compartidos AWS → despliegue y verificación.
Cada transición elimina una limitación de la etapa anterior. Esta vista explicativa
no sustituye un modelo ArchiMate formal ni una entrega completa de TOGAF si se exigen.

## 15. Cómo explicarlo en un minuto

“GraphWord conecta palabras que cambian una letra. Uso patrones para repartir la
construcción sin perder conexiones. La API registra trabajos; SQS los reparte;
dos workers calculan particiones; S3 guarda archivos y DynamoDB decide qué resultados
están confirmados. Un reconciliador recupera trabajos tras fallos. Un reductor une
las particiones y la API permite consultar el grafo. He separado pruebas simuladas
de la demostración real en AWS. Repartir la construcción no significa distribuir
también las consultas ni haber demostrado una mejora de velocidad.”

## Lecturas oficiales utilizadas

- [DynamoDB: transacciones](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html).
- [DynamoDB: escritura condicional](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutItem.html).
- [SQS: entrega al menos una vez](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html).
- [SSM: acceso sin puertos entrantes](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html).
- [Credenciales temporales](https://docs.aws.amazon.com/cli/latest/userguide/cli-authentication-short-term.html).
