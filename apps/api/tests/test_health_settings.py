import pytest
from contract.errors import ConfigError
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine

from app.main import create_app
from app.settings import Settings, normalize_database_url


def test_api_health_matches_contract(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "contract_version": "0.1.0", "model_adapter": "mock"}
    assert r.headers["X-Request-ID"] and r.headers["x-content-type-options"] == "nosniff"  # A5


def test_healthz_and_readyz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_readyz_db_down_is_503_without_leaking(settings: Settings) -> None:
    bad: Engine = create_engine("sqlite:////nonexistent-dir/definitely/not/here.db")
    r = TestClient(create_app(settings, db_engine=bad)).get("/readyz")
    assert r.status_code == 503 and r.json() == {"status": "not_ready", "checks": {"database": "error"}}
    assert "nonexistent" not in r.text


def test_request_id_echo_and_replacement(client: TestClient) -> None:
    assert client.get("/healthz", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"
    bad = client.get("/healthz", headers={"X-Request-ID": "x y\t;"}).headers["X-Request-ID"]
    assert bad != "x y\t;" and len(bad) == 32


def test_cors_allows_web_origin_only(client: TestClient) -> None:  # A1
    ok = client.options(
        "/api/workflows", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options(
        "/api/workflows", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in bad.headers
    assert "access-control-allow-credentials" not in ok.headers


def test_cors_wildcard_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_cors_env_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings(_env_file=None).cors_origins == ["http://a.test", "http://b.test"]


def test_defaults_fail_closed() -> None:
    s = Settings(_env_file=None)
    assert s.liferescue_env == "production" and s.model_adapter == "nebius"


def test_env_names_follow_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIFERESCUE_ENV", "local")
    monkeypatch.setenv("LIFERESCUE_MODEL_ADAPTER", "mock")
    s = Settings(_env_file=None)
    assert (s.liferescue_env, s.model_adapter, s.docs_enabled) == ("local", "mock", True)


def test_startup_blocks_mock_adapter_in_production_and_staging() -> None:  # contract guard, composition root
    for env in ("production", "prod", "staging"):
        with pytest.raises(ConfigError):
            create_app(
                Settings(_env_file=None, liferescue_env=env, model_adapter="mock", database_url="sqlite://")
            )


def test_startup_nebius_needs_key_and_never_echoes_it(monkeypatch: pytest.MonkeyPatch) -> None:  # K1
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    with pytest.raises(ConfigError) as exc:
        create_app(
            Settings(
                _env_file=None, liferescue_env="production", model_adapter="nebius", database_url="sqlite://"
            )
        )
    assert "NEBIUS_API_KEY" in str(exc.value)
    monkeypatch.setenv("NEBIUS_API_KEY", "canary-not-a-real-key-0123456789")
    app = create_app(
        Settings(
            _env_file=None, liferescue_env="production", model_adapter="nebius", database_url="sqlite://"
        )
    )
    c = TestClient(app)
    assert c.get("/api/health").json()["model_adapter"] == "nebius"
    assert (
        c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    )  # A2: docs off when deployed


def test_database_url_normalised_to_psycopg3() -> None:
    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("sqlite://") == "sqlite://"


def test_startup_refuses_builtin_dev_database_url_when_deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "canary-not-a-real-key-0123456789")
    for env in ("production", "prod", "staging"):
        with pytest.raises(ConfigError) as exc:
            create_app(Settings(_env_file=None, liferescue_env=env, model_adapter="nebius"))
        assert "DATABASE_URL" in str(exc.value) and "liferescue_dev" not in str(exc.value)
    # an explicit URL (here SQLite, no connection is made at startup) is accepted
    create_app(
        Settings(
            _env_file=None, liferescue_env="production", model_adapter="nebius", database_url="sqlite://"
        )
    )


def test_broker_package_without_redaction_module_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from app.security import keys

    real = importlib.import_module

    def fake(name: str, package: str | None = None):  # type: ignore[no-untyped-def]
        if name.endswith(".redaction"):
            raise ModuleNotFoundError(name)
        return real(name, package)

    monkeypatch.setattr(importlib, "import_module", fake)
    assert keys._load_broker_module() is None
