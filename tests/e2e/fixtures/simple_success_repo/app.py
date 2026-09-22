"""Simple Pydantic v1 application."""

from pydantic import BaseModel


class Model(BaseModel):
    name: str
    age: int


def create_model(name: str, age: int) -> Model:
    obj = {"name": name, "age": age}
    return BaseModel.parse_obj(obj)


def main() -> None:
    model = create_model("Alice", 30)
    print(Model.dict())


if __name__ == "__main__":
    main()
