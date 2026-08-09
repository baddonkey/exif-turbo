from __future__ import annotations

from ..models.tgm import TgmConcept


class TgmPromptBuilder:
    VERSION = 1
    _MAX_ALIASES = 6

    def build(self, concept: TgmConcept) -> str:
        aliases = sorted(
            {
                alias.strip()
                for alias in concept.aliases
                if alias.strip() and alias.casefold() != concept.label.casefold()
            },
            key=str.casefold,
        )[: self._MAX_ALIASES]
        prompt = f"A photograph depicting {concept.label.strip()}"
        if aliases:
            prompt += "; also known as " + ", ".join(aliases)
        return prompt + "."