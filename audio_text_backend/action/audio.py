import logging
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from audio_text_backend.config import Config
from audio_text_backend.errors import FileValidationError, StorageError

logger = logging.getLogger(__name__)


def validate_audio_file(filename: str, content_type: str, file_size: int) -> None:
    """Validate uploaded audio file."""
    # Check file size
    max_size_mb = int(Config.file.max_size_mb)
    if file_size > max_size_mb * 1024 * 1024:
        raise FileValidationError(
            message=f"File size exceeds {max_size_mb}MB limit",
            file_size=file_size,
            max_size=max_size_mb * 1024 * 1024,
        )

    # Basic audio type check
    if not content_type.startswith("audio/"):
        raise FileValidationError(message="File must be an audio file", content_type=content_type)

    # Check extension
    extension = filename.split(".")[-1].lower()
    allowed_extensions = Config.file.allowed_audio_extensions.split(",")
    if extension not in allowed_extensions:
        raise FileValidationError(
            message=f"Unsupported audio format. Allowed: {Config.file.allowed_audio_extensions}",
            extension=extension,
            allowed_extensions=allowed_extensions,
        )


class S3Storage:
    """S3-compatible storage handler."""

    def __init__(self):
        self.client: boto3.client = boto3.client(
            "s3",
            aws_access_key_id=Config.aws.access_key,
            aws_secret_access_key=Config.aws.secret_key,
            region_name=Config.aws.region,
        )
        self.bucket_name = Config.aws.bucket_name
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """Create bucket if it doesn't exist."""
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                self._create_bucket()

    def _create_bucket(self):
        try:
            self.client.create_bucket(Bucket=self.bucket_name)
            logger.info(f"Created S3 bucket: {self.bucket_name}")
        except ClientError as e:
            logger.error(f"Failed to create bucket: {e}")
            raise StorageError(message="Could not create S3 bucket", error=str(e))

    def download_file(self, key: str, file_path: Path) -> None:
        """Download file from S3."""
        try:
            self.client.download_file(self.bucket_name, key, str(file_path))
            logger.info(f"Downloaded file from S3: {key}")
        except ClientError as e:
            logger.error(f"Failed to download file from S3: {e}")
            raise StorageError(message="Could not download file from S3", key=key, error=str(e))

    def delete_file(self, key: str) -> None:
        """Delete file from S3."""
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=key)
            logger.info(f"Deleted file from S3: {key}")
        except ClientError as e:
            logger.error(f"Failed to delete file from S3: {e}")
            raise StorageError(message="Could not delete file from S3", key=key, error=str(e))

    def file_exists(self, key: str) -> bool:
        """Check if file exists in S3."""
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise StorageError(message="Could not check file existence", key=key, error=str(e))

    def get_presigned_url(self, key: str, content_type: str, expiration: int = 3600) -> str:
        """Generate presigned URL for file access."""
        try:
            return self.client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=expiration,
                HttpMethod="PUT",
            )
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise StorageError(message="Could not generate presigned URL", key=key, error=str(e))


storage = S3Storage()
