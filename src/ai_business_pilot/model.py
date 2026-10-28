"""Shared language-model configuration."""

from langchain_ollama import ChatOllama


def create_chat_model() -> ChatOllama:
    """Create the local Ollama model used by the project."""
    return ChatOllama(
        model="qwen3:4b-instruct",
        temperature=0,
    )
