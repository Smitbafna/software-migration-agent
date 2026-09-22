"""Application with behavior change needing manual review."""
from pydantic import BaseModel

class Model(BaseModel):
    name: str
    age: int

    def is_adult(self) -> bool:
        # Behavior change - semantics may differ between v1 and v2
        return self.age >= 18

def check_model(model: Model) -> bool:
    return model.is_adult()
