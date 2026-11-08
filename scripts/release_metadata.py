import os
import re


def release_tags(event: str, ref: str, sha: str) -> list[str]:
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Expected a full commit SHA")
    if event == "workflow_dispatch":
        return ["sha-" + sha]
    match = re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", ref)
    if not match:
        raise ValueError("Release requires a stable SemVer tag such as v1.2.3")
    major, minor, patch = match.groups()
    return [f"{major}.{minor}.{patch}", f"{major}.{minor}", "latest", "sha-" + sha]


def main():
    tags = release_tags(
        os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF_NAME"], os.environ["GITHUB_SHA"]
    )
    image = "ghcr.io/" + os.environ["GITHUB_REPOSITORY"].lower()
    immutable = [tag for tag in tags if tag.startswith("sha-") or tag.count(".") == 2]
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"image={image}\n")
        output.write(
            "tags<<IMAGE_TAGS\n" + "\n".join(f"{image}:{tag}" for tag in tags) + "\nIMAGE_TAGS\n"
        )
        output.write(f"immutable_tags={','.join(immutable)}\n")


if __name__ == "__main__":
    main()
