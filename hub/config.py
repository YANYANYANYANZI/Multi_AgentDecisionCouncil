from __future__ import annotations

import os
from dataclasses import dataclass, replace

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://api.deepseek.com"
    agent_s_base_url: str = "https://api.deepseek.com"
    agent_a_base_url: str = "https://api.deepseek.com"
    agent_b_base_url: str = "https://api.deepseek.com"
    agent_c_base_url: str = "https://api.deepseek.com"
    summary_base_url: str = "https://api.deepseek.com"
    agent_s_model: str = "deepseek-chat"
    agent_a_model: str = "deepseek-chat"
    agent_b_model: str = "deepseek-chat"
    agent_c_model: str = "deepseek-chat"
    summary_model: str = "deepseek-chat"
    shared_api_key: str = ""
    agent_s_api_key: str = ""
    agent_a_api_key: str = ""
    agent_b_api_key: str = ""
    agent_c_api_key: str = ""
    summary_api_key: str = ""
    export_dir: str = "exports"


def load_settings(
    base_url: str | None = None,
    agent_s_model: str | None = None,
    agent_a_model: str | None = None,
    agent_b_model: str | None = None,
    agent_c_model: str | None = None,
    summary_model: str | None = None,
    shared_api_key: str | None = None,
    agent_s_base_url: str | None = None,
    agent_a_base_url: str | None = None,
    agent_b_base_url: str | None = None,
    agent_c_base_url: str | None = None,
    summary_base_url: str | None = None,
    agent_s_api_key: str | None = None,
    agent_a_api_key: str | None = None,
    agent_b_api_key: str | None = None,
    agent_c_api_key: str | None = None,
    summary_api_key: str | None = None,
) -> Settings:
    def provided(value: str | None, fallback: str) -> str:
        return fallback if value is None else value

    shared_key = (
        provided(shared_api_key, "")
        or os.getenv("SHARED_API_KEY", "")
        or os.getenv("SHARED_DEEPSEEK_API_KEY", "")
        or os.getenv("ARK_API_KEY", "")
    )
    settings = Settings(
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
        agent_s_base_url=os.getenv("AGENT_S_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")),
        agent_a_base_url=os.getenv("AGENT_A_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")),
        agent_b_base_url=os.getenv("AGENT_B_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")),
        agent_c_base_url=os.getenv("AGENT_C_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")),
        summary_base_url=os.getenv("SUMMARY_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")),
        agent_s_model=os.getenv("AGENT_S_MODEL", os.getenv("MODEL_NAME", "deepseek-chat")),
        agent_a_model=os.getenv("AGENT_A_MODEL", os.getenv("MODEL_NAME", "deepseek-chat")),
        agent_b_model=os.getenv("AGENT_B_MODEL", os.getenv("MODEL_NAME", "deepseek-chat")),
        agent_c_model=os.getenv("AGENT_C_MODEL", os.getenv("MODEL_NAME", "deepseek-chat")),
        summary_model=os.getenv("SUMMARY_MODEL", os.getenv("MODEL_NAME", "deepseek-chat")),
        shared_api_key=shared_key,
        agent_s_api_key=provided(agent_s_api_key, os.getenv("AGENT_S_API_KEY", shared_key)),
        agent_a_api_key=provided(agent_a_api_key, os.getenv("AGENT_A_API_KEY", shared_key)),
        agent_b_api_key=provided(agent_b_api_key, os.getenv("AGENT_B_API_KEY", shared_key)),
        agent_c_api_key=provided(agent_c_api_key, os.getenv("AGENT_C_API_KEY", shared_key)),
        summary_api_key=provided(summary_api_key, os.getenv("SUMMARY_API_KEY", shared_key)),
        export_dir=os.getenv("EXPORT_DIR", "exports"),
    )
    return replace(
        settings,
        base_url=provided(base_url, settings.base_url),
        agent_s_base_url=provided(agent_s_base_url, settings.agent_s_base_url),
        agent_a_base_url=provided(agent_a_base_url, settings.agent_a_base_url),
        agent_b_base_url=provided(agent_b_base_url, settings.agent_b_base_url),
        agent_c_base_url=provided(agent_c_base_url, settings.agent_c_base_url),
        summary_base_url=provided(summary_base_url, settings.summary_base_url),
        agent_s_model=provided(agent_s_model, settings.agent_s_model),
        agent_a_model=provided(agent_a_model, settings.agent_a_model),
        agent_b_model=provided(agent_b_model, settings.agent_b_model),
        agent_c_model=provided(agent_c_model, settings.agent_c_model),
        summary_model=provided(summary_model, settings.summary_model),
        shared_api_key=provided(shared_api_key, settings.shared_api_key),
        agent_s_api_key=provided(agent_s_api_key, settings.agent_s_api_key),
        agent_a_api_key=provided(agent_a_api_key, settings.agent_a_api_key),
        agent_b_api_key=provided(agent_b_api_key, settings.agent_b_api_key),
        agent_c_api_key=provided(agent_c_api_key, settings.agent_c_api_key),
        summary_api_key=provided(summary_api_key, settings.summary_api_key),
    )
