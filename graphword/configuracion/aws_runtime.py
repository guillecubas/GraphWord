"""Leer configuración del entorno sin incluir claves secretas en el código."""
import os
import boto3
from botocore.config import Config
from graphword.almacenamiento.aws_storage import AWSJobRepository, S3GraphRepository


def repositories():
    # boto3 busca credenciales en el perfil local o en el rol de la instancia.
    session = boto3.Session(region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    endpoint = os.getenv("GRAPHWORD_AWS_ENDPOINT")  # Solo usar LocalStack si se configura.
    config = Config(connect_timeout=3, read_timeout=10,
                    retries={"mode": "standard", "total_max_attempts": 2})
    s3_client = session.client("s3", endpoint_url=endpoint, config=config)
    objects = S3GraphRepository(s3_client, os.environ["GRAPHWORD_BUCKET"])
    dynamodb = session.resource("dynamodb", endpoint_url=endpoint, config=config)
    table = dynamodb.Table(os.environ["GRAPHWORD_TABLE"])
    # El tiempo HTTP debe superar los diez segundos de espera de SQS.
    queue_config = config.merge(Config(read_timeout=25))
    sqs_client = session.client("sqs", endpoint_url=endpoint, config=queue_config)
    jobs = AWSJobRepository(
        table,
        sqs_client,
        os.environ["GRAPHWORD_QUEUE_URL"],
        objects,
    )
    return objects, jobs
