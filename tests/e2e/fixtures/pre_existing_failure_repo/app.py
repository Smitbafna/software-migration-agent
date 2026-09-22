"""Application with pre-existing test failure."""
from pydantic import BaseModel

class Model(BaseModel):
    name: str

    def greet(self) -> str:
        return f"Hello, {self.name}!"

def test_greeting():
    obj = {"name": "Alice"}
    model = BaseModel.parse_obj(obj)
    assert model.greet() == "Hello, Alice!"
