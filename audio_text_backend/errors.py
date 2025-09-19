from typing import Any


class Error(Exception):
    code: int
    reason: str
    description: str

    def __init__(self, **data: Any):
        self.data = data

    def __str__(self):
        fields = [
            ("code", self.code),
            ("reason", self.reason),
            ("data", repr(self.data)),
        ]
        fields_repr = ", ".join(f"{field}={value}" for field, value in fields)
        return fields_repr


class DBError(Error):
    code = 900
    reason = "db-error"
    description = "Error occurred while performing a database action."


class NoDataFound(Error):
    code = 1000
    reason = "no-data-found"
    description = "No data found in DB."


class FileValidationError(Error):
    code = 1100
    reason = "file-validation-error"
    description = "File validation failed."


class FileProcessingError(Error):
    code = 1200
    reason = "file-processing-error"
    description = "Error occurred while processing file."


class StorageError(Error):
    code = 1300
    reason = "storage-error"
    description = "Error occurred while accessing storage."


class TranscriptionError(Error):
    code = 1400
    reason = "transcription-error"
    description = "Error occurred during audio transcription."
