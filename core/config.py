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
    # Open-weight, Apache 2.0 - the weights are published and this runs locally
    # under Ollama. "openai/" is the publisher, not a hosted proprietary model.
    # Chosen over qwen/qwen3.6-27b after benchmarking: ~25x lower latency and
    # ~7x fewer tokens per question, because Qwen spends most of a call on
    # reasoning tokens that translating a question into SQL does not need.
    model_name: str = "openai/gpt-oss-120b"

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

    # Blank means the parameter is not sent at all. Providers disagree on the
    # accepted values ("none" vs "low"/"medium"/"high"), and the default is
    # already fast for gpt-oss. The planner drops it automatically if rejected.
    reasoning_effort: str = ""

    # Serial pacing between questions in the eval harness. The free tier is
    # burst-limited per minute, and 43 back-to-back calls exhaust it.
    eval_delay_seconds: float = 0.5


settings = Settings()
