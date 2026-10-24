"""Thin async client for a chat model deployed in Microsoft Foundry (Azure OpenAI).

Configure with environment variables (see .env.example):
    AZURE_OPENAI_ENDPOINT      https://<resource>.openai.azure.com/
    AZURE_OPENAI_API_KEY       key from the Foundry project / Azure OpenAI resource
    AZURE_OPENAI_DEPLOYMENT    deployment name, e.g. gpt-4o-mini
    AZURE_OPENAI_API_VERSION   optional, defaults below

If these are missing, `LLMClient.from_env()` returns None and the app uses its
template narration instead, so everything still runs offline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

log = logging.getLogger(__name__)

DEFAULT_API_VERSION = "2024-10-21"


class LLMClient:
    def __init__(self, endpoint: str, api_key: str, deployment: str, api_version: str = DEFAULT_API_VERSION,
                 timeout: float = 12.0, max_concurrency: int = 4):
        from openai import AsyncAzureOpenAI

        self.client = AsyncAzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version, timeout=timeout)
        self.deployment = deployment
        self.sem = asyncio.Semaphore(max_concurrency)

    @classmethod
    def from_env(cls) -> "LLMClient | None":
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        key = os.getenv("AZURE_OPENAI_API_KEY")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        if not (endpoint and key and deployment):
            return None
        try:
            return cls(endpoint, key, deployment, os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION))
        except Exception as exc:
            log.warning("LLM disabled: %s", exc)
            return None

    async def complete_json(self, system: str, user: str, max_tokens: int = 300) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        async with self.sem:
            try:
                resp = await self.client.chat.completions.create(
                    model=self.deployment, messages=messages, response_format={"type": "json_object"},
                    max_tokens=max_tokens, temperature=0.6,
                )
            except Exception as exc:
                # Reasoning-style deployments reject max_tokens/temperature; retry with their parameters.
                if "max_tokens" not in str(exc) and "temperature" not in str(exc):
                    raise
                resp = await self.client.chat.completions.create(
                    model=self.deployment, messages=messages, response_format={"type": "json_object"},
                    max_completion_tokens=max_tokens * 4,
                )
        text = resp.choices[0].message.content or "{}"
        return json.loads(text)
