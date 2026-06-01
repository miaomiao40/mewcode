"""Prompt management — modular system prompt, injections, environment context."""

from mewcode.prompts.loader import PromptModule, load_modules, load_injection
from mewcode.prompts.builder import PromptBuilder
from mewcode.prompts.injector import PromptInjector
from mewcode.prompts.environment import collect_environment

__all__ = [
    "PromptModule",
    "PromptBuilder",
    "PromptInjector",
    "collect_environment",
    "load_modules",
    "load_injection",
]
