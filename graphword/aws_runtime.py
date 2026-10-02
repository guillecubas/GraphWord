"""Configuration from environment; never accept or persist inline AWS secrets."""
import os
import boto3
from botocore.config import Config
from graphword.aws_storage import AWSJobRepository, S3GraphRepository


def repositories():
    session = boto3.Session(region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    endpoint = os.getenv("GRAPHWORD_AWS_ENDPOINT")  # Explicit LocalStack opt-in only.
    config = Config(connect_timeout=3, read_timeout=10,
                    retries={"mode": "standard", "total_max_attempts": 2})
    objects = S3GraphRepository(session.client("s3", endpoint_url=endpoint, config=config),
                                os.environ["GRAPHWORD_BUCKET"])
    table = session.resource("dynamodb", endpoint_url=endpoint, config=config).Table(os.environ["GRAPHWORD_TABLE"])
    # The HTTP read timeout must exceed SQS's ten-second long poll.
    queue_config = config.merge(Config(read_timeout=25))
    jobs = AWSJobRepository(table, session.client("sqs", endpoint_url=endpoint, config=queue_config),
                            os.environ["GRAPHWORD_QUEUE_URL"], objects)
    return objects, jobs
