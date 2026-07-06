FROM eclipse-temurin:21-jre

WORKDIR /app

COPY target/graphword-1.0.0.jar app.jar
COPY data ./data

EXPOSE 8080

CMD ["java", "-jar", "app.jar"]
