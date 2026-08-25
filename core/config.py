from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration. Every tunable lives here, nothing reads os.environ directly."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Groq serves open-weight models behind an OpenAI-compatible API.
    # Swapping to Ollama or Together is a base_url + model_name change, nothing else.
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    model_name: str = "llama-3.3-70b-versatile"

    # Caps. Every one of these exists because an unbounded version of it
    # is a way for a single question to take down the app.
    max_rows_returned: int = 5000
    query_timeout_seconds: int = 10
    max_repair_attempts: int = 2
    max_upload_mb: int = 50
    sample_values_per_column: int = 5
    max_join_candidates: int = 8
    min_join_overlap: float = 0.5
    max_bar_categories: int = 25

    llm_temperature: float = 0.0  # SQL generation should be reproducible
    llm_timeout_seconds: int = 30


settings = Settings()
