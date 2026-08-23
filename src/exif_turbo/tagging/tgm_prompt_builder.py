from __future__ import annotations

from ..models.vocabulary import VocabularyConcept


class TgmPromptBuilder:
    VERSION = 4
    STRATEGY = "wikidata-locale-prompts-max-pool-v1"
    LOCALES = ("en", "de", "fr", "it")
    _MAX_ALIASES_PER_LOCALE = 4
    _MAX_LABEL_LENGTH = 160
    _MAX_ALIAS_LENGTH = 80
    MAX_PROMPT_LENGTH = 600

    _TEMPLATES = {
        "en": ("A photograph depicting {label}", "aliases"),
        "de": ("Ein Foto mit {label}", "Synonyme"),
        "fr": ("Une photographie représentant {label}", "alias"),
        "it": ("Una fotografia raffigurante {label}", "alias"),
    }

    def build(self, concept: VocabularyConcept, locale: str) -> str:
        if locale not in self.LOCALES:
            raise ValueError(f"unsupported prompt locale: {locale}")
        terms = concept.terms(locale)
        preferred_label = terms.preferred_label.strip()[: self._MAX_LABEL_LENGTH]
        aliases = sorted(
            {
                alias.strip()[: self._MAX_ALIAS_LENGTH]
                for alias in terms.aliases
                if alias.strip()
                and alias.casefold() != terms.preferred_label.casefold()
            },
            key=lambda alias: (alias.casefold(), alias),
        )[: self._MAX_ALIASES_PER_LOCALE]
        template, alias_label = self._TEMPLATES[locale]
        prompt = template.format(label=preferred_label)
        if aliases:
            separator = " :" if locale == "fr" else ":"
            prompt += f" ({alias_label}{separator} " + ", ".join(aliases) + ")"
        prompt += "."
        if len(prompt) > self.MAX_PROMPT_LENGTH:
            raise ValueError("controlled-vocabulary prompt exceeded its size bound")
        return prompt

    def build_all(self, concept: VocabularyConcept) -> tuple[tuple[str, str], ...]:
        return tuple(
            (locale, self.build(concept, locale)) for locale in self.LOCALES
        )