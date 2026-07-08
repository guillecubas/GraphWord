# GraphWord

GraphWord es una API REST en Java para construir y consultar grafos de palabras.

Cada palabra es un nodo. Dos palabras se conectan con una arista cuando tienen la misma longitud y solo cambia una letra, por ejemplo `cat` y `bat`.

El proyecto incluye diccionarios locales de 3, 4 y 5 letras para probar el funcionamiento basico del grafo.

## Tecnologias

- Java 21
- Spring Boot
- Maven
- Docker
- Prometheus / Micrometer

## Ejecutar en local

```powershell
mvn clean package
mvn spring-boot:run
```

La API queda disponible en:

```text
http://localhost:8080
```

## Endpoints principales

```text
GET  /health
GET  /dictionaries
POST /graph/load?dictionary=words3
POST /graph/load?dictionary=words4
POST /graph/load?dictionary=word_medium
GET  /graph/summary
GET  /graph/shortest?from=cat&to=dad
GET  /graph/paths?from=cat&to=dad&limit=20
GET  /graph/longest-path?from=cat&to=dad
GET  /graph/isolated
GET  /graph/degree/{degree}
GET  /graph/highest-degree
GET  /graph/clusters
GET  /actuator/prometheus
```

## Prueba rapida

```powershell
curl http://localhost:8080/dictionaries
curl -X POST http://localhost:8080/graph/load
curl -X POST "http://localhost:8080/graph/load?dictionary=word_medium"
curl http://localhost:8080/graph/summary
curl "http://localhost:8080/graph/shortest?from=cat&to=dad"
curl "http://localhost:8080/graph/longest-path?from=cat&to=dad"
```

## Docker

```powershell
mvn clean package
docker build -t graphword .
docker run -p 8080:8080 graphword
```

## Tests

```powershell
mvn clean verify
```

## Observabilidad y carga

Prometheus esta disponible mediante Spring Boot Actuator:

```powershell
curl http://localhost:8080/actuator/prometheus
```
