from pydantic import BaseModel


class FileGeneratePresignedUrlResponse(BaseModel):
    """Schema for creating a presigned url to upload on AWS."""

    url: str
