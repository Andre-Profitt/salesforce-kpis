"""Application configuration."""

import os
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional


class SalesforceConfig(BaseModel):
    """Salesforce connection configuration."""
    instance_url: str = Field(..., env='SF_INSTANCE_URL')
    client_id: str = Field(..., env='SF_CLIENT_ID')
    username: str = Field(..., env='SF_USERNAME')
    private_key_path: str = Field(..., env='SF_PRIVATE_KEY_PATH')
    api_version: str = Field(default='59.0', env='SF_API_VERSION')

    @property
    def aud(self) -> str:
        """Audience for JWT - login.salesforce.com for production."""
        if 'salesforce.com' in self.instance_url:
            return 'https://login.salesforce.com'
        return self.instance_url


class CDCConfig(BaseModel):
    """CDC/Pub-Sub configuration."""
    use_pubsub: bool = Field(default=True, env='CDC_USE_PUBSUB')
    poll_interval: int = Field(default=60, env='CDC_POLL_INTERVAL')
    replay_store_path: str = Field(default='.replay.json', env='CDC_REPLAY_STORE')

    channels: list[str] = Field(default_factory=lambda: [
        '/data/LeadChangeEvent',
        '/data/TaskChangeEvent',
        '/data/EmailMessageChangeEvent'
    ])


class FlywheelConfig(BaseModel):
    """Flywheel logging configuration."""
    client_id: str = Field(default='salesforce-prod', env='FLYWHEEL_CLIENT_ID')
    jsonl_path: str = Field(default='.flywheel.jsonl', env='FLYWHEEL_JSONL_PATH')
    elasticsearch_url: Optional[str] = Field(default=None, env='FLYWHEEL_ES_URL')
    elasticsearch_index: str = Field(default='flywheel-logs', env='FLYWHEEL_ES_INDEX')


class MetricsConfig(BaseModel):
    """Metrics and observability configuration."""
    port: int = Field(default=8080, env='METRICS_PORT')
    host: str = Field(default='0.0.0.0', env='METRICS_HOST')


class AppConfig(BaseModel):
    """Main application configuration."""
    environment: str = Field(default='development', env='ENVIRONMENT')
    log_level: str = Field(default='INFO', env='LOG_LEVEL')

    salesforce: SalesforceConfig
    cdc: CDCConfig
    flywheel: FlywheelConfig
    metrics: MetricsConfig


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    from dotenv import load_dotenv
    load_dotenv()

    return AppConfig(
        salesforce=SalesforceConfig(
            instance_url=os.getenv('SF_INSTANCE_URL'),
            client_id=os.getenv('SF_CLIENT_ID'),
            username=os.getenv('SF_USERNAME'),
            private_key_path=os.getenv('SF_PRIVATE_KEY_PATH'),
            api_version=os.getenv('SF_API_VERSION', '59.0')
        ),
        cdc=CDCConfig(),
        flywheel=FlywheelConfig(),
        metrics=MetricsConfig()
    )
