from datetime import time

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict, TomlConfigSettingsSource


class EndpointConfig(BaseModel):
    name: str
    model: str
    region: str
    capacity_tps: int


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", toml_file="config.toml")

    pt_endpoints: list[EndpointConfig]
    pt_num_retries: int = 3
    pt_monitor_interval: int = 60
    pt_monitor_failure_threshold: int = 5
    monitor_samples_enabled: bool = True
    pt_night_window_start_utc: time = time(hour=22)
    pt_night_window_end_utc: time = time(hour=6)
    max_reschedules: int = 5
    day_queue_concurrency: int = 10
    night_queue_concurrency: int = 3

    gcp_project: str
    database_url: str

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        return (
            kwargs["init_settings"],
            kwargs["env_settings"],
            TomlConfigSettingsSource(settings_cls),
        )

    def endpoint_by_model(self, model: str) -> EndpointConfig | None:
        matches = [ep for ep in self.pt_endpoints if ep.model == model]
        if len(matches) == 1:
            return matches[0]
        return None

    def endpoint_by_name(self, name: str) -> EndpointConfig | None:
        for ep in self.pt_endpoints:
            if ep.name == name:
                return ep
        return None
