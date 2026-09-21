"""Example user repository application using Pydantic v1."""

from pydantic import BaseModel, Field, validator


class User(BaseModel):
    id: int
    name: str = Field(..., regex="^[A-Za-z]+$")

    class Config:
        orm_mode = True
        allow_mutation = False

    @validator("name")
    def validate_name(cls, v, field, config):
        if not v:
            raise ValueError("Name cannot be empty")
        return v


def main():
    data = {"id": 1, "name": "Alice"}
    user = User.parse_obj(data)
    print("User dict:", user.dict())
    print("Fields:", User.__fields__)


if __name__ == "__main__":
    main()
