# Validación de la entrega ampliada

Fecha: 2 de octubre de 2026. Rama: `refactor/python-distributed`.
Consultar primero la [guía fácil](guia-proyecto.md) y la
[matriz del enunciado](rubric-mapping.md).

## Resumen comprobado

| Comprobación | Resultado | Evidencia |
|---|---|---|
| Suite local Python 3.12.14 | 72 tests, sin fallos ni errores | `python -m unittest discover -s tests -q` |
| CI Python 3.11 y 3.12 | Ambos jobs `success` | Run enlazado abajo, artefactos unittest |
| CD GitHub → AWS | `skipped`, no habilitado | Bloqueo IAM documentado; no equivale a despliegue aprobado |
| Corpus de dos fuentes | 16491 palabras, 3–8 letras | Manifiesto, avisos y test de hashes/intersección |
| Smoke HTTP AWS | Éxito, dos workers, grafo idéntico | `aws-hardening-2026-10-02.json` |
| Replay HTTP / conflicto | Mismo job; otro contenido devuelve 409 | Smoke remoto y tests |
| Benchmark local | 60 construcciones, todas correctas | `benchmark-local.json` |
| Benchmark AWS | 24 construcciones, todas correctas | `benchmark-aws.json` |

CI del commit funcional `0d791c6`:
[GitHub Actions 37019469154](https://github.com/guillecubas/GraphWord/actions/runs/37019469154).
Tests completados a las 14:23 UTC. Los cuatro tests del orquestador CD simulan sus
llamadas para comprobar secuencia y limpieza; no simulan autorización OIDC real.

## Cambios y comprobaciones nuevas

`aeace97`: renovación de leases, idempotencia, fuentes trazables y pruebas.
`0d791c6`: medición comparativa, empaquetado de corpus, pipeline OIDC condicionado y
pruebas de su orquestador. La documentación y evidencias se versionan por separado.

Respecto de las 58 pruebas iniciales, se añaden ocho pruebas de robustez/corpus,
dos del adaptador AWS y cuatro del orquestador de despliegue. Las anteriores
siguen pasando. Moto comprueba contratos sin gasto AWS; no demuestra permisos,
latencia ni disponibilidad real. Las pruebas de renovación prolongada son locales
controladas; el smoke remoto no fuerza un trabajo de más de 300 segundos.

## Despliegue real verificado

Se actualizaron las pilas de GraphWord, reemplazando únicamente los nodos de
aplicación y sus discos de despliegue. Los datos S3/DynamoDB permanecieron.
Versión final del artefacto:
`303c6e037519d3ec85c66c5ccdf21d1a429c6ddd2988e9315f261ec70224a6aa`.
SSM comprobó cloud-init terminado y los servicios activos en ambos nodos.

Durante la verificación apareció un timeout de SQS: el timeout HTTP no superaba
su espera larga. Se corrigió a 25 segundos para un long poll de 10 y se desplegó
otra vez antes del smoke y del benchmark. Los resultados finales corresponden
a la versión corregida, no al primer intento.

Prueba SSM `64134c6f-8e76-43af-b501-6485377bda62`, estado `Success`, salida 0:

- Trabajo `84752143-22e9-5115-8a38-884a7d129264`, `SUCCEEDED`.
- Grafo `701d94ba-aeb8-4a98-a8cd-317ba2d91c9e`: 7 nodos, 8 aristas.
- Particiones 0, 1, 5, 6 en `ip-172-31-92-43.ec2.internal`; 2, 3, 4, 7 en
  `ip-172-31-89-69.ec2.internal`.
- Camino por HTTP `cat → bat → bad → dad`, aislado `zzz`.
- Igualdad de toda la adyacencia, replay idempotente y conflicto 409 comprobados.

[Evidencia resumida](evidence/aws-hardening-2026-10-02.json). Las salidas SSM completas
se guardan localmente en `var/aws-status.json` y `var/aws-smoke.json`, sin credenciales.
La primera demostración se conserva como [informe histórico](aws-validation.md).

## Rendimiento

La comparación AWS observa una mejora de 1,39–1,46× usando dos workers frente a uno
en estos conjuntos. El [informe](performance.md) especifica muestras, medianas,
cadencia experimental y límites. No se infiere autoescalado, SLA o rendimiento
para conjuntos arbitrariamente grandes.

## Lo que todavía requiere una decisión externa

No hay proveedor/rol OIDC autorizado para GitHub en el laboratorio y el estudiante
no tiene permisos para crearlo. El job CD existe y se omite deliberadamente hasta
configurar variables y rol. La [guía CD](continuous-deployment.md) explica la acción
del profesor/admin o la aceptación de despliegue manual reproducible con CI.
No se han almacenado claves temporales en GitHub ni ampliado permisos del LabRole.

No se afirma completar requisitos de producción: no hay API redundante o pública
autenticada, autoscaling, recolector de objetos huérfanos ni monitorización continua
con alarmas. Los límites de búsquedas combinatorias se informan en la respuesta.

## Preparar la defensa

1. Mostrar la matriz del enunciado y las dos capas arquitectónicas.
2. Mostrar corpus, licencias y diferencia entre normalización y filtro léxico.
3. Arrancar nodos y ejecutar `status` y `smoke` siguiendo `aws-operations.md`.
4. Mostrar una consulta completa y otra limitada (`complete=false`).
5. Mostrar CI, evidencia de dos workers y benchmark sin prometer aceleración lineal.
6. Explicar el bloqueo de CD con transparencia y detener EC2 al terminar.

Las máquinas no se dejan encendidas para mantener una URL activa. Parar EC2 conserva
los datos y reduce consumo, pero EBS/S3/DynamoDB pueden seguir consumiendo crédito.
Tras las pruebas se verificó `stopped` para `i-05a79853ef71179e4` (API/worker A)
y `i-0b66f969b2eb343bd` (worker B). El benchmark restauró previamente los servicios;
volverán a arrancar con systemd al encender las máquinas. La API está apagada hasta
ejecutar `start` y comprobar `status`.
