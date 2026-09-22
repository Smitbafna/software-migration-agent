"""Business logic."""
from .models import Model

def process_model(data: dict) -> Model:
    obj = data
    return BaseModel.parse_obj(obj)

def serialize_model(model: Model) -> dict:
    return Model.dict()
