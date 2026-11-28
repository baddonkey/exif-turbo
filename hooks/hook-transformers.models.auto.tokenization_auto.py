"""Include dynamically resolved modules for the supported XLM-R tokenizer."""
from PyInstaller import isolated


@isolated.decorate
def _xlm_roberta_tokenizer_modules():
    from transformers.models.auto.configuration_auto import model_type_to_module_name
    from transformers.models.auto.tokenization_auto import TOKENIZER_MAPPING_NAMES

    return [
        "transformers.models." + model_type_to_module_name(model_type)
        for model_type, tokenizer in TOKENIZER_MAPPING_NAMES.items()
        if tokenizer == "XLMRobertaTokenizer"
    ]


hiddenimports = _xlm_roberta_tokenizer_modules()
