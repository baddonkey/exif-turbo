"""Offline checks executed by the frozen application before packaging."""
from __future__ import annotations

import json
import os
import tempfile
import traceback
from pathlib import Path


def run_release_smoke_test(report: Path) -> None:
    """Check packaged dependencies and encrypted Vec1 using only temporary data."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        _check_runtime()
    except Exception:
        report.write_text(
            json.dumps({"status": "failed", "error": traceback.format_exc()}),
            encoding="utf-8",
        )
        raise SystemExit(1)
    report.write_text(json.dumps({"status": "passed"}), encoding="utf-8")


def _check_runtime() -> None:
    import certifi
    import numpy as np
    from open_clip.tokenizer import HFTokenizer
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import XLMRobertaTokenizerFast

    from ..data.ai_vec1_repository import AiVec1Repository
    from ..data.image_index_repository import ImageIndexRepository
    from ..models.ai_model_profile import DEFAULT_AI_MODEL_PROFILE
    from .vec1_extension import bundled_vec1_extension

    if not Path(certifi.where()).is_file():
        raise RuntimeError("The packaged HTTPS certificate bundle is missing")
    extension = bundled_vec1_extension()
    with tempfile.TemporaryDirectory(prefix="exif-turbo-smoke-") as work:
        root = Path(work)
        backend = Tokenizer(WordLevel({
            "<s>": 0, "<pad>": 1, "</s>": 2, "<unk>": 3,
            "dog": 4, "car": 5, "house": 6, "bottle": 7,
        }, unk_token="<unk>"))
        backend.pre_tokenizer = Whitespace()
        tokenizer_dir = root / "tokenizer"
        XLMRobertaTokenizerFast(tokenizer_object=backend).save_pretrained(tokenizer_dir)
        tokenizer = HFTokenizer(
            str(tokenizer_dir), local_files_only=True, context_length=8,
        )
        tokens = tokenizer(["bottle", "dog"])
        if tokens.shape != (2, 8) or tokens[0].equal(tokens[1]):
            raise RuntimeError("The packaged text tokenizer is not working")

        database = root / "index.db"
        password = "temporary-release-smoke-key"
        paths = [str(root / "first.jpg"), str(root / "second.jpg")]
        images = ImageIndexRepository(database, key=password)
        try:
            for path in paths:
                images.upsert_image(path, Path(path).name, 1.0, 100, {}, "")
        finally:
            images.close()

        vectors = np.zeros((2, DEFAULT_AI_MODEL_PROFILE.dimension), dtype=np.float32)
        vectors[0, 0] = vectors[1, 1] = 1.0
        repository = AiVec1Repository(database, password, extension)
        try:
            repository.load()
            repository.add_images(vectors, paths)
        finally:
            repository.close()
        repository = AiVec1Repository(database, password, extension)
        try:
            repository.load()
            hits = repository.search_filtered(vectors[0], set(paths), threshold=0.5)
            if len(hits) != 1 or hits[0][0] != paths[0] or abs(hits[0][1] - 1.0) > 1e-6:
                raise RuntimeError("The packaged Vec1 search returned incorrect results")
        finally:
            repository.close()
        if database.read_bytes().startswith(b"SQLite format 3"):
            raise RuntimeError("The smoke-test database is not encrypted")
