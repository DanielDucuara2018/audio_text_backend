import logging
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from audio_text_backend.config import Config

logger = logging.getLogger(__name__)


def validate_audio_file(filename: str, content_type: str, file_size: int) -> None:
    """Validate uploaded audio file."""
    # Check file size
    if file_size > int(Config.file.max_size_mb) * 1024 * 1024:
        raise Exception(f"File size exceeds {Config.file.max_size_mb}MB limit")

    # Basic audio type check
    if not content_type.startswith("audio/"):
        raise Exception("File must be an audio file")

    # Check extension
    extension = filename.split(".")[-1].lower()
    if extension not in Config.file.allowed_audio_extensions.split(","):
        raise Exception(
            f"Unsupported audio format. Allowed: {Config.file.allowed_audio_extensions}"
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
        """Create bucket if it doesn"t exist."""
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
            raise Exception("Could not create S3 bucket") from e

    def download_file(self, key: str, file_path: Path) -> None:
        """Download file from S3."""
        try:
            self.client.download_file(self.bucket_name, key, file_path)
            logger.info(f"Downloaded file from S3: {key}")
        except ClientError as e:
            logger.error(f"Failed to download file from S3: {e}")
            raise Exception("Could not download file from S3") from e

    def delete_file(self, key: str) -> None:
        """Delete file from S3."""
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=key)
            logger.info(f"Deleted file from S3: {key}")
        except ClientError as e:
            logger.error(f"Failed to delete file from S3: {e}")
            raise Exception("Could not delete file from S3") from e

    def get_presigned_url(self, key: str, content_type: str, expiration: int = 3600) -> str | None:
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
            raise Exception("Could not generate presigned URL") from e


storage = S3Storage()
