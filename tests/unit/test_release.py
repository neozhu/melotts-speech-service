import pytest

from scripts.release_metadata import main


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_publish_only_latest_without_version_or_sha(monkeypatch, tmp_path, event):
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_REPOSITORY", "Owner/MeloTTS-Speech-Service")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    main()
    assert output.read_text(encoding="utf-8") == (
        "image=ghcr.io/owner/melotts-speech-service\n"
        "tag=ghcr.io/owner/melotts-speech-service:latest\n"
    )
