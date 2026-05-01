from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://marketpulse:marketpulse@localhost:5432/marketpulse"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security
    SECRET_KEY: str = "dev-secret-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Alpha Vantage
    ALPHA_VANTAGE_API_KEY: str = ""

    # Rate limiting
    DEFAULT_RATE_LIMIT_REQUESTS: int = 60
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # App
    DEBUG: bool = False
    APP_VERSION: str = "1.0.0"


settings = Settings()
