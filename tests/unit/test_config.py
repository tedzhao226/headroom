from datetime import time

from headroom.core.config import EndpointConfig, Settings


def test_settings_parses_utc_night_window_fields() -> None:
    settings = Settings(
        pt_endpoints=[],
        gcp_project="test-project",
        database_url="postgresql://localhost/test",
        pt_night_window_start_utc="22:00",
        pt_night_window_end_utc="06:00",
    )
    assert settings.pt_night_window_start_utc == time(hour=22)
    assert settings.pt_night_window_end_utc == time(hour=6)


def test_settings_default_num_retries() -> None:
    settings = Settings(
        pt_endpoints=[],
        gcp_project="test-project",
        database_url="postgresql://localhost/test",
    )
    assert settings.pt_num_retries == 3
    assert settings.max_reschedules == 5
    assert settings.day_queue_concurrency == 10
    assert settings.night_queue_concurrency == 3


def test_endpoint_by_model_unique() -> None:
    ep = EndpointConfig(name="flash-us", model="gemini-2.5-flash", region="us-central1", capacity_tps=5000)
    settings = Settings(
        pt_endpoints=[ep],
        gcp_project="test-project",
        database_url="postgresql://localhost/test",
    )
    assert settings.endpoint_by_model("gemini-2.5-flash") is ep
    assert settings.endpoint_by_model("nonexistent") is None


def test_endpoint_by_model_returns_none_when_ambiguous() -> None:
    ep1 = EndpointConfig(name="flash-us", model="gemini-2.5-flash", region="us-central1", capacity_tps=5000)
    ep2 = EndpointConfig(name="flash-eu", model="gemini-2.5-flash", region="europe-west1", capacity_tps=2000)
    settings = Settings(
        pt_endpoints=[ep1, ep2],
        gcp_project="test-project",
        database_url="postgresql://localhost/test",
    )
    assert settings.endpoint_by_model("gemini-2.5-flash") is None
    assert settings.endpoint_by_name("flash-us") is ep1
