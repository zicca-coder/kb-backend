from typing import Annotated, Any

from pydantic import BeforeValidator, Field, PlainSerializer, WithJsonSchema

SNOWFLAKE_ID_PATTERN = r"^[1-9][0-9]*$"


def validate_snowflake_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("snowflake ID must be a positive integer string")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError("snowflake ID must be positive")
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or not normalized.isdecimal():
            raise ValueError("snowflake ID must be a positive integer string")
        if normalized.startswith("0"):
            raise ValueError("snowflake ID must not contain leading zeros")
        return int(normalized)
    raise ValueError("snowflake ID must be a positive integer string")


SnowflakeId = Annotated[
    int,
    BeforeValidator(validate_snowflake_id),
    PlainSerializer(lambda value: str(value), return_type=str),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": SNOWFLAKE_ID_PATTERN,
            "examples": ["2038429384729382912"],
        }
    ),
    Field(gt=0),
]
