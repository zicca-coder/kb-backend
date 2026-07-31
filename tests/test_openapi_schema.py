from fastapi.testclient import TestClient


def test_snowflake_user_ids_are_documented_as_strings(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()["components"]["schemas"]

    assert schema["CurrentUserResponse"]["properties"]["id"]["type"] == "string"
    assert schema["UserRead"]["properties"]["id"]["type"] == "string"
    assert schema["UserAgentRead"]["properties"]["user_id"]["type"] == "string"
    assert schema["UserAgentRead"]["properties"]["id"]["type"] == "integer"
