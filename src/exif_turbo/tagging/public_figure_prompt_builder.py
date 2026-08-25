from __future__ import annotations

from .tgm_prompt_builder import TgmPromptBuilder


class PublicFigurePromptBuilder(TgmPromptBuilder):
    VERSION = 1
    STRATEGY = "wikidata-public-figure-names-v1"
    _TEMPLATES = {
        "en": ("A photograph of {label}", "also known as"),
        "de": ("Ein Foto von {label}", "auch bekannt als"),
        "fr": ("Une photographie de {label}", "aussi connu comme"),
        "it": ("Una fotografia di {label}", "noto anche come"),
    }