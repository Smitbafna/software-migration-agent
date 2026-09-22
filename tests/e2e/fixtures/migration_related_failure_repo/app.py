"""Application where migration will cause test failure."""
from pydantic import BaseModel

class Model(BaseModel):
    name: str
    age: int

    def is_adult(self) -> bool:
        # This behavior changes in v2 - age threshold or logic differs
        return self.age >= 18

def test_adult_check():
    obj = {"name": "Bob", "age": 17}
    model = BaseModel.parse_obj(obj)
    # In v2, this might fail if behavior changes
    assert model.is_adult() == False
