import urllib.error
from unittest.mock import MagicMock, Mock

import pytest

from scripts import check_registry_tags


def test_immutable_tag_check_fails_closed(monkeypatch):
    for name, value in {
        "IMAGE": "ghcr.io/owner/service",
        "REGISTRY_USER": "user",
        "REGISTRY_PASSWORD": "secret",
        "IMMUTABLE_TAGS": "1.2.3,sha-" + "a" * 40,
    }.items():
        monkeypatch.setenv(name, value)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"token":"token"}'
    opener = Mock(
        side_effect=[
            response,
            urllib.error.HTTPError("url", 404, "missing", {}, None),
            urllib.error.HTTPError("url", 401, "denied", {}, None),
        ]
    )
    monkeypatch.setattr(check_registry_tags.urllib.request, "urlopen", opener)
    with pytest.raises(RuntimeError, match="401"):
        check_registry_tags.main()


@pytest.mark.parametrize("exists", [True, False])
def test_existing_tag_is_rejected_and_missing_tag_is_allowed(monkeypatch, exists):
    for name, value in {
        "IMAGE": "ghcr.io/owner/service",
        "REGISTRY_USER": "user",
        "REGISTRY_PASSWORD": "secret",
        "IMMUTABLE_TAGS": "1.2.3",
    }.items():
        monkeypatch.setenv(name, value)
    token = MagicMock()
    token.__enter__.return_value.read.return_value = b'{"token":"token"}'
    head = MagicMock() if exists else urllib.error.HTTPError("url", 404, "missing", {}, None)
    monkeypatch.setattr(
        check_registry_tags.urllib.request, "urlopen", Mock(side_effect=[token, head])
    )
    if exists:
        with pytest.raises(RuntimeError, match="already exists"):
            check_registry_tags.main()
    else:
        check_registry_tags.main()
