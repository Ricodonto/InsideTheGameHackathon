"""Thin async client for the chat model behind narration and "Ask the match".

Two providers, configured with environment variables (see .env.example):

Microsoft Foundry (Azure OpenAI), used first when set:
    AZURE_OPENAI_ENDPOINT      https://<resource>.openai.azure.com/
    AZURE_OPENAI_API_KEY       key from the Foundry project / Azure OpenAI resource
    AZURE_OPENAI_DEPLOYMENT    deployment name, e.g. gpt-4o-mini
    AZURE_OPENAI_API_VERSION   optional, defaults below

Any OpenAI-compatible API (fallback if no Azure subscription is available):
    OPENAI_API_KEY             key for that provider
    OPENAI_BASE_URL            optional, the provider's OpenAI-compatible URL (omit for OpenAI itself)
    OPENAI_MODEL               model name, e.g. gpt-4o-mini

If neither is set, `LLMClient.from_env()` returns None and the app uses its
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
    def __init__(self, client, model: str, provider: str, max_concurrency: int = 4):
        self.client = client
        self.model = model
        self.provider = provider
        self.sem = asyncio.Semaphore(max_concurrency)

    @classmethod
    def from_env(cls) -> "LLMClient | None":
        try:
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            key = os.getenv("AZURE_OPENAI_API_KEY")
            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
            if endpoint and key and deployment:
                from openai import AsyncAzureOpenAI

                client = AsyncAzureOpenAI(
                    azure_endpoint=endpoint,
                    api_key=key,
                    api_version=os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION),
                    timeout=12.0,
                )
                return cls(client, deployment, "Foundry")
            key = os.getenv("OPENAI_API_KEY")
            if key:
                from openai import AsyncOpenAI

                client = AsyncOpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None, api_key=key, timeout=12.0)
                return cls(client, os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "OpenAI-compatible")
        except Exception as exc:
            log.warning("LLM disabled: %s", exc)
        return None

    async def complete_json(self, system: str, user: str, max_tokens: int = 300) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        async with self.sem:
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model, messages=messages, response_format={"type": "json_object"},
                    max_tokens=max_tokens, temperature=0.6,
                )
            except Exception as exc:
                # Reasoning-style models reject max_tokens/temperature; retry with their parameters.
                if "max_tokens" not in str(exc) and "temperature" not in str(exc):
                    raise
                resp = await self.client.chat.completions.create(
                    model=self.model, messages=messages, response_format={"type": "json_object"},
                    max_completion_tokens=max_tokens * 4,
                )
        text = resp.choices[0].message.content or "{}"
        return json.loads(text)
