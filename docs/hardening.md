# Reintentos seguros y reservas renovables

## 1. Idempotency-Key: no crear dos trabajos por reenviar

Problema: el servidor registra una petición, pero el cliente pierde la respuesta.
Si reenvía el mismo POST sin identificarlo, se crean dos trabajos.

Solución: enviar una clave nueva por operación lógica y reutilizarla solo para
reintentar esa misma operación. Ejemplo PowerShell:

```powershell
$body = @{ words = @('cat','bat','bad','dad'); partitions = 8 } | ConvertTo-Json
$headers = @{ 'Idempotency-Key' = 'demo-construccion-001' }
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/jobs/partitioned-builds -ContentType application/json -Headers $headers -Body $body
# Repetir la misma llamada recupera el mismo job_id.
```

La clave se convierte en ID estable por tipo de trabajo. Se guarda también una
huella del contenido normalizado: palabras sin duplicados, particiones y máximo
de intentos cuando aplica. Mismo contenido devuelve el trabajo existente;
contenido diferente, 409. No basta con comparar solo la clave.

Memoria usa bloqueo; SQLite registra clave y trabajos en la misma transacción;
DynamoDB usa escritura/transacción condicional y relee al ganador de una carrera.
Memoria pierde claves al reiniciar; SQLite/AWS las conservan mientras existan sus
registros. No hay TTL de claves. El ámbito es compartido por repositorio/tipo,
no por usuario: no existe todavía un modelo multitenant/autenticación.
El ID estable no es un secreto ni un mecanismo de autorización.

La opción cubre `/v1/jobs/graph-builds` y `/v1/jobs/partitioned-builds`.
Sin cabecera, cada petición sigue siendo una operación nueva. Una clave repetida
después de un fallo devuelve ese trabajo fallido; usar otra clave para una nueva
operación. Esto evita duplicar el registro lógico, no promete ejecución física
exactamente una vez ni elimina objetos S3 huérfanos de una carrera.

## 2. Heartbeat: renovar mientras se calcula

Problema: una reserva fija puede vencer mientras un worker sano calcula un grafo
grande. El reconciliador podría reintentarlo innecesariamente.

Solución: un hilo de renovación espera aproximadamente un tercio de la duración
del lease y comprueba que el token, worker y estado siguen vigentes. Renueva la
fecha; en AWS también amplía la visibilidad del mensaje SQS. No incrementa intentos.
Solo reclamar un nuevo intento los incrementa.

Al terminar el cálculo se detiene y espera al hilo antes de confirmar. Una
renovación fallida impide publicar éxito; el trabajo queda recuperable por
caducidad. No se cancela por fuerza el cálculo Python en curso. Si el proceso
muere, deja de renovar y el reconciliador recupera el trabajo tras vencer el lease.
Un token viejo nunca recupera la propiedad de un intento nuevo.

El cliente AWS limita conexión/lectura y reintentos. SQS usa 25 segundos de lectura
para superar su long poll de 10 segundos; el lease remoto es de 300 segundos.
Los timeouts no garantizan progreso ante cualquier fallo de sistema/red; la
condición persistente sigue siendo la barrera de confirmación.

## 3. Qué se ha probado

Tests locales: reenvíos concurrentes, conflicto HTTP, persistencia SQLite, lease
extendido, rechazo de token caducado, trabajo lento que renueva y error de
renovación que no confirma. Moto: idempotencia de ambos tipos AWS y renovación
sin incrementar intentos. El smoke real comprueba replay y conflicto 409 mediante
HTTP además de igualdad del grafo. Las búsquedas y sus límites tienen tests propios.

Las pruebas pequeñas remotas no fuerzan una construcción de más de 300 segundos:
la renovación prolongada se comprueba de forma controlada en tests, no se afirma
haber simulado una caída real de AWS. Permanecen los límites de memoria, escaneos
de tabla, objetos huérfanos, autenticación pública y disponibilidad de la API.
