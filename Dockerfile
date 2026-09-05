FROM python:3.12-slim
WORKDIR /app
COPY graphword ./graphword
COPY data ./data
USER 65534:65534
CMD ["python", "-m", "graphword", "data/words3.txt", "--partitions", "4", "--from", "cat", "--to", "dad"]
