"""Trusted immutable upstream assets. No request can supply a repository or path."""

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger("speech")

FRONTEND_REVISIONS = {
    "bert-base-multilingual-uncased": "7cbf9a625e29989f6b9c6c2fa68234c304f7e38f",
    "bert-base-uncased": "86b5e0934494bd15c9632b12f734a8a67f723594",
    "tohoku-nlp/bert-base-japanese-v3": "65243d6e5629b969c77309f217bd7b1a79d43c7e",
    "kykim/bert-kor-base": "1779cc0982ada0216dd6de0dd4e86fb78201926d",
    "dbmdz/bert-base-french-europeana-cased": "b895c3cf291f7bf4c15639078a6bee0b3e272c5b",
    "dccuchile/bert-base-spanish-wwm-uncased": "d1c9c4565c9d6731e57ed7f027b802697bad861e",
}

ACOUSTIC_MODELS = {
    "ZH": {
        "repo": "myshell-ai/MeloTTS-Chinese",
        "revision": "af5d207a364ea4208c6f589c89f57f88414bdd16",
        "files": {
            "config.json": "d58b5acdab89ad2bbd65325affab309ae3cb964834b02f9a60587474e81c8bb9",
            "checkpoint.pth": "a74e9eadffff065c75eb6dfa040efa72cad23e72cfea70d39190bc174fb97093",
        },
    },
    "EN": {
        "repo": "myshell-ai/MeloTTS-English",
        "revision": "bb4fb7346d566d277ba8c8c7dbfdf6786139b8ef",
        "files": {
            "config.json": "039116c927c70eaa4458d315ea83aaaa99e1fca1c621b50c8ca56b4a5700eb77",
            "checkpoint.pth": "acd278040eaf9536908e2b965273df5a731c44d8f0da66cc5fed7972772ed23c",
        },
    },
}


def pretrained_options(repo: str) -> dict:
    """Used by the installation patch on official frontend from_pretrained calls."""
    return {"revision": FRONTEND_REVISIONS[repo], "trust_remote_code": False}


def verify_sha256(path: str | Path, expected: str):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("Model asset checksum mismatch; clear the affected cached snapshot.")


def acoustic_paths(language: str) -> dict[str, str]:
    from huggingface_hub import hf_hub_download

    model = ACOUSTIC_MODELS[language]
    paths = {}
    for filename, digest in model["files"].items():
        logger.info("model_asset_loading", extra={"language": language, "asset": filename})
        path = hf_hub_download(repo_id=model["repo"], revision=model["revision"], filename=filename)
        verify_sha256(path, digest)
        paths[filename] = path
    return paths
