"""Application with multiple usages."""
from pydantic import BaseModel, ConfigDict

class Model(BaseModel):
    name: str

    class Config:
        orm_mode = True

def create_model(name: str) -> Model:
    obj = {"name": name}
    return BaseModel.parse_obj(obj)

def get_model_dict(model: Model) -> dict:
    return Model.dict()
