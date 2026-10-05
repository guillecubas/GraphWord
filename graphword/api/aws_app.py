from graphword.api.routes import create_app
from graphword.configuracion.aws_runtime import repositories
from graphword.almacenamiento.aws_storage import S3DictionaryRepository
import os

# Preparar los adaptadores compartidos por todas las peticiones.
graphs, jobs = repositories()
catalog_key = os.getenv("GRAPHWORD_DICTIONARY_CATALOG")
# Sin catálogo configurado, las operaciones de diccionarios no están disponibles.
dictionaries = None
if catalog_key:
    dictionaries = S3DictionaryRepository(graphs.client, graphs.bucket, catalog_key)
app = create_app(graphs, jobs, storage_label="aws-s3-dynamodb-sqs", partitioned_builds=jobs,
                 dictionary_repository=dictionaries)
