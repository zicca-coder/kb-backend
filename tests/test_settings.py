from app.core.settings import Settings


def make_settings(**overrides) -> Settings:
    values = {
        "db_name": "darwin_knowledge_test",
        "db_user": "tester",
        "db_password": "secret",
        "jwt_secret_key": "test-only-jwt-secret-key-with-sufficient-length",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_log_levels_are_normalized_from_env_style_values() -> None:
    settings = make_settings(
        log_level="debug",
        sqlalchemy_log_level="error",
    )

    assert settings.log_level == "DEBUG"
    assert settings.sqlalchemy_log_level == "ERROR"


def test_sql_echo_is_independent_from_app_debug() -> None:
    settings = make_settings(app_debug=True)

    assert settings.app_debug is True
    assert settings.sql_echo is False


def test_sql_echo_can_be_enabled_explicitly() -> None:
    settings = make_settings(sql_echo=True)

    assert settings.sql_echo is True
