from graphword.api import create_app
from graphword.aws_runtime import repositories

graphs, jobs = repositories()
app = create_app(graphs, jobs, storage_label="aws-s3-dynamodb-sqs", partitioned_builds=jobs)
