FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY graphword ./graphword
COPY data ./data
RUN pip install --no-cache-dir .
RUN mkdir /data && chown 65534:65534 /data
ENV GRAPHWORD_DB_PATH=/data/graphword.db
USER 65534:65534
EXPOSE 8000
CMD ["uvicorn", "graphword.local_app:app", "--host", "0.0.0.0", "--port", "8000"]
