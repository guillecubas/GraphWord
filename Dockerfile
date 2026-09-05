FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY graphword ./graphword
COPY data ./data
RUN pip install --no-cache-dir .
USER 65534:65534
EXPOSE 8000
CMD ["uvicorn", "graphword.api:app", "--host", "0.0.0.0", "--port", "8000"]
