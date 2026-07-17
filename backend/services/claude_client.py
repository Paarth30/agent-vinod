"""Lazy singleton Anthropic client, built the same way every steps/*.py file does."""
import anthropic
import config as cfg

_client = None


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=cfg.GEMINI_API_KEY)
    return _client
