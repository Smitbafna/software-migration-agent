"""Data models."""
from pydantic import BaseModel

class Model(BaseModel):
    name: str
    email: str

    def get_dict(self) -> dict:
        return Model.dict()
