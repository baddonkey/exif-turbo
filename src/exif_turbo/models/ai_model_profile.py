from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AiModelProfile:
    identifier: str
    model_name: str
    pretrained: str
    dimension: int
    multilingual: bool = False
    requires_legacy_bpe: bool = False

    @property
    def model_ref(self) -> str:
        if self.model_name.startswith("hf-hub:"):
            return self.model_name
        return self.model_name


LEGACY_OPENAI_CLIP_PROFILE = AiModelProfile(
    identifier="openai-clip-vit-b-32-v1",
    model_name="ViT-B-32",
    pretrained="openai",
    dimension=512,
    requires_legacy_bpe=True,
)

MULTILINGUAL_CLIP_PROFILE = AiModelProfile(
    identifier="openclip-xlm-r-b32-laion5b-v1",
    model_name="xlm-roberta-base-ViT-B-32",
    pretrained="laion5b_s13b_b90k",
    dimension=512,
    multilingual=True,
)

DEFAULT_AI_MODEL_PROFILE = MULTILINGUAL_CLIP_PROFILE