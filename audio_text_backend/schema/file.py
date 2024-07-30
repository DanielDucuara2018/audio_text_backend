from typing import Optional

from pydantic import BaseModel


class fileRequest(BaseModel):

    filename: Optional[str] = None
    mode: str = "medium"


class terminateRequest(BaseModel):

    pid: Optional[int] = None
