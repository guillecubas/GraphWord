# Enunciado → implementación → evidencia

Interpretación del enunciado facilitado por el estudiante, 2 de octubre de 2026.
El texto general permite LocalStack, pero el entregable concreto pide una API en
AWS: por eso se ha realizado además una demostración en AWS real.

| Requisito | Implementación / evidencia | Alcance y límite |
|---|---|---|
| Python y GitHub | Paquete `graphword`, tests, historial de commits | Rama `refactor/python-distributed` |
| Aristas por una letra distinta | Patrones estables y conjuntos en `graph.py` | Solo misma longitud y ASCII |
| Diferentes fuentes de palabras | SCOWL/Hunspell + CMUdict, manifiesto y licencias | `data/curated/README.md` |
| Pronunciables y significativas | Intersección léxica y pronunciación registrada | Criterio operativo; no validación semántica perfecta |
| Empezar con 3 letras y ampliar | Corpus 3–8, tamaños/densidades y benchmark local | AWS compara 3–6; no millones de nodos |
| Camino mínimo | BFS a través de API | Sin pesos; equivalente en distancia a Dijkstra con pesos 1 |
| Todos los caminos | Enumeración de caminos simples | Exacta solo cuando `complete=true`; límites explícitos |
| Camino más largo sin ciclos entre dos nodos | Búsqueda de mejor camino simple | No es diámetro BFS; óptimo solo con búsqueda completa |
| Clústeres densamente conectados | Componentes del k-core | Criterio de grado interno mínimo, no comunidades Louvain |
| Alto grado, grado elegido, aislados | Consultas de grados y resumen | Tests de motor y HTTP |
| API desplegada en AWS | EC2 + SSM, S3/DynamoDB/SQS | API privada por túnel; máquinas se detienen al acabar |
| Aplicación y tecnología con framework empresarial | `enterprise-architecture.md` | ADM adaptado y conceptos ArchiMate, no certificación formal |
| Configuración reproducible | CloudFormation, ZIP por SHA y scripts | AMI/transitivas no totalmente fijadas |
| Pruebas automáticas mediante CI/CD | Matriz GitHub Actions y artefactos de tests | CI activa; CD AWS preparado pero bloqueado por IAM |
| Escalabilidad y distribución | Comparación controlada 1/2 y IDs de workers | No implica autoescalado ni alta disponibilidad |

## Criterios que conviene explicar en la defensa

El enunciado menciona Dijkstra o A* como ejemplos: BFS es exacto y más sencillo en
un grafo no ponderado. Si se añaden costes distintos a las aristas, habrá que
cambiar el algoritmo y el contrato.

Enumerar todos los caminos simples y garantizar el más largo puede ser inviable
en grafos grandes. La API informa del truncamiento; no sustituye silenciosamente
el camino simple más largo por el mayor de los caminos mínimos. Demostrar
completitud en un ejemplo pequeño y límites en uno grande es parte de la entrega.

Un k-core puede ser grande y tener densidad global baja; “clúster” aquí significa
región con un mínimo de vecinos internos. No se afirma maximizar densidad ni
detectar comunidades óptimas. Si el profesor exige otro criterio, sería una
ampliación a acordar, no una propiedad ya demostrada.

## Pendiente externo para cerrar CI/CD completo

Habilitar un rol OIDC de GitHub necesita permisos no disponibles en Academy.
El [documento CD](continuous-deployment.md) contiene el procedimiento y la
limitación. Hace falta que el profesor/admin lo autorice o acepte expresamente
CI automática y despliegue manual reproducible. No se inventa evidencia de CD.
