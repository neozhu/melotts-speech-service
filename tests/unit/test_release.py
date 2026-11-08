import pytest

from scripts.release_metadata import release_tags


def test_semver_tags():
    assert release_tags("push", "v1.2.3", "a" * 40) == ["1.2.3", "1.2", "latest", "sha-" + "a" * 40]


def test_manual_only_pushes_sha():
    assert release_tags("workflow_dispatch", "main", "a" * 40) == ["sha-" + "a" * 40]


@pytest.mark.parametrize("tag", ["v1.2", "v01.2.3", "v1.2.3-rc.1", "v1.2.3;evil", "main"])
def test_invalid_release_tag_is_rejected(tag):
    with pytest.raises(ValueError):
        release_tags("push", tag, "a" * 40)
