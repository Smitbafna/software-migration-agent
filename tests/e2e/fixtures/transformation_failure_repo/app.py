"""Application that will cause transformation failure."""
from pydantic import BaseModel

class Model(BaseModel):
    name: str

def test() -> Model:
    # This will fail because BaseModel.parse_obj is not called
    model = Model(name="test")
    return model
