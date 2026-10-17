from __future__ import annotations

from care_task_agent.config import Settings


def test_defaults() -> None:
    settings = Settings()
    assert settings.fhir_base_url.startswith("https://")
    assert settings.port == 8080
    assert settings.fhir_token is None


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("FHIR_BASE_URL", "https://example.test/fhir")
    monkeypatch.setenv("FHIR_TOKEN", "secret")
    monkeypatch.setenv("PORT", "9000")
    settings = Settings.from_env()
    assert settings.fhir_base_url == "https://example.test/fhir"
    assert settings.fhir_token == "secret"
    assert settings.port == 9000


def test_blank_token_is_none(monkeypatch) -> None:
    monkeypatch.setenv("FHIR_TOKEN", "")
    assert Settings.from_env().fhir_token is None
