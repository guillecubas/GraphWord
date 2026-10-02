"""Configuration from environment; never accept or persist inline AWS secrets."""
import os
import boto3
from graphword.aws_storage import AWSJobRepository, S3GraphRepository


def repositories():
    session = boto3.Session(region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    endpoint = os.getenv("GRAPHWORD_AWS_ENDPOINT")  # Explicit LocalStack opt-in only.
    objects = S3GraphRepository(session.client("s3", endpoint_url=endpoint),
                                os.environ["GRAPHWORD_BUCKET"])
    table = session.resource("dynamodb", endpoint_url=endpoint).Table(os.environ["GRAPHWORD_TABLE"])
    jobs = AWSJobRepository(table, session.client("sqs", endpoint_url=endpoint),
                            os.environ["GRAPHWORD_QUEUE_URL"], objects)
    return objects, jobs
