# Rendimiento y evolución del grafo

Fecha: 2 de octubre de 2026. Son experimentos exploratorios reproducibles, no una
garantía de latencia ni una prueba de millones de nodos. Se compara la misma
entrada y ocho particiones con uno y dos workers (strong scaling).

## 1. Corpus y estructura

Fuente: intersección SCOWL/Hunspell–CMUdict; [filtros y licencias](../data/curated/README.md).
Densidad de grafo simple no dirigido: `2 × aristas / (nodos × (nodos − 1))`.

| Letras | Nodos | Aristas | Densidad | Componentes | Aislados |
|---|---:|---:|---:|---:|---:|
| 3 | 628 | 3815 | 0,0193775 | 12 | 8 |
| 4 | 1889 | 7153 | 0,0040113 | 117 | 89 |
| 5 | 2677 | 3171 | 0,0008853 | 823 | 640 |
| 6 | 3676 | 2332 | 0,0003452 | 2164 | 1766 |
| 7 | 3898 | 1187 | 0,0001563 | 3053 | 2677 |
| 8 | 3723 | 432 | 0,0000624 | 3327 | 3033 |

Más letras no significa necesariamente más palabras ni más conexiones. En este
corpus, la densidad cae y aumentan los aislados. La entrada de ocho letras tiene
menos nodos que la de siete. Son observaciones de este filtro y estas fuentes,
no una ley universal de los grafos de palabras. Aumentar longitud incrementa
también el trabajo de creación de patrones aunque disminuyan las aristas.

## 2. Procesos locales

Windows 10, Python 3.12.14, ocho procesadores lógicos; cinco repeticiones por modo
y longitud. Se alterna orden 1→2 / 2→1. `ProcessPoolExecutor` usa `spawn` en ambos
casos. El tiempo incluye arranque, construcción de particiones, comunicación,
unión y cierre del pool. Excluye lectura del fichero y cálculo/comparación de la
referencia. Se valida igualdad completa de adyacencia en cada repetición.

| Letras | Mediana 1 proceso (s) | Mediana 2 procesos (s) | Cociente T1/T2 |
|---|---:|---:|---:|
| 3 | 0,2978 | 0,2823 | 1,055 |
| 4 | 0,4540 | 0,3789 | 1,198 |
| 5 | 0,5748 | 0,4348 | 1,322 |
| 6 | 0,7479 | 0,5492 | 1,362 |
| 7 | 0,8781 | 0,6109 | 1,437 |
| 8 | 0,8976 | 0,6374 | 1,408 |

60 construcciones comprobadas. Evidencia con muestras individuales, tiempo CPU
sumado de particiones y hashes: [benchmark-local.json](evidence/benchmark-local.json).
Es paralelismo en un equipo, no una medida de comunicación entre máquinas.

## 3. Dos máquinas AWS reales

Dos EC2 `t3.micro`, Amazon Linux 2023, Python 3.11, región `us-east-1`.
Un worker reside con API/reconciliación; el segundo está en otra máquina. Mismos
S3, DynamoDB y SQS en ambos modos. Se desactiva únicamente el segundo worker para
el modo de uno; no se sustituuye AWS por memoria. Tres repeticiones por modo y
longitud, orden alternado, 24 construcciones en total.

Para controlar la espera del coordinador, se pausa su servicio de 30 segundos y
el driver reconcilia en ambos modos con una espera de 0,5 segundos entre pasadas
(el tiempo de la pasada se suma). Al terminar se restauran ambos servicios.
No hay otros trabajos pendientes al iniciar el experimento.

El cronómetro remoto incluye envío HTTP, persistencia, cola, cálculo, reducción,
reconciliación y polling. Excluye envío de la orden SSM, arranque/parada del servicio,
lectura del corpus, referencia y descarga/comparación final. Todas las adyacencias
coinciden. Se observó un ID de worker en todos los ensayos de uno y dos IDs en todos
los ensayos de dos; todas las particiones terminaron en un intento.

| Letras | Mediana 1 worker (s) | Mediana 2 workers (s) | Cociente T1/T2 |
|---|---:|---:|---:|
| 3 | 1,9656 | 1,4171 | 1,387 |
| 4 | 1,9871 | 1,4236 | 1,396 |
| 5 | 2,1578 | 1,4811 | 1,457 |
| 6 | 2,0838 | 1,4975 | 1,392 |

Evidencia: [benchmark-aws.json](evidence/benchmark-aws.json), con IDs de trabajos,
grafos, workers, intentos, hashes y muestras. La mejora observada es aproximadamente
1,39–1,46×; no se afirma duplicar rendimiento al duplicar workers.

## 4. Interpretación y límites

La coordinación y el I/O pesan mucho en estos grafos pequeños. No puede atribuirse
todo el ahorro a CPU. El polling introduce cuantización; tres repeticiones son
pocas y no se han calculado intervalos de confianza. El orden alternado reduce un
sesgo sistemático, pero no elimina variabilidad de red, caché o carga de AWS.

Las t3 son burstables y no se registró el saldo de créditos CPU. El worker A
comparte recursos con la API/driver. La tabla conserva trabajos anteriores y crece
entre pruebas; el reconciliador hace escaneos completos. Tampoco se aísla el coste
del reductor ni se mide memoria máxima. No hay prueba de carga sostenida, múltiples
clientes, escalado automático o disponibilidad ante caída de una zona.

Los tiempos AWS **no son la latencia habitual con reconciliación cada 30 segundos**.
El smoke de la configuración normal tardó unos 52 segundos entre registro y éxito.
La optimización de la cadencia del experimento no se ha aplicado como un cambio
silencioso de producción. Local y AWS miden cosas distintas; no comparar sus
segundos como si fueran el mismo entorno.

## 5. Repetir

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_local.py --repeats 5
.\.venv\Scripts\python.exe scripts/aws_operations.py start --profile default
.\.venv\Scripts\python.exe scripts/aws_operations.py status --profile default
.\.venv\Scripts\python.exe scripts/benchmark_aws.py --profile default --repeats 3
.\.venv\Scripts\python.exe scripts/aws_operations.py stop --profile default
```

Esperar disponibilidad SSM antes de `status`. El benchmark AWS necesita el último
release con corpus y script remoto. No ejecutarlo durante una demo o con otros
workers conectados: pausa servicios y exige que no existan trabajos sin terminar.
Regenera los JSON de evidencia; conservar los originales con Git si se comparan
fechas. La restauración de servicios no detiene EC2: el último comando sí lo pide.
