"""Application with unrelated code that resembles old API."""
from pydantic import BaseModel

class Model(BaseModel):
    name: str

# This is NOT a pydantic usage - just a string that happens to contain "parse_obj"
def some_function():
    docstring = "This function used to call parse_obj but now it does not."
    return "parse_obj is mentioned here but not used"

def actual_usage():
    obj = {"name": "Bob"}
    model = BaseModel.parse_obj(obj)
    return model
