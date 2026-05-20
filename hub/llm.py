from __future__ import annotations

import json
from typing import Any

from openai import OpenAI


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model_name: str, temperature: float = 0.4) -> None:
        if not api_key:
            raise ValueError("至少需要配置一个 API Key。请在 `.env` 中填写 `SHARED_DEEPSEEK_API_KEY` 或三个 Agent 独立 Key。")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name
        self.temperature = temperature

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=self.temperature,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
