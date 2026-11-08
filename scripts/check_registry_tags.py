"""Refuse to overwrite exact SemVer or SHA tags; fail closed on registry errors."""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def main():
    image = os.environ["IMAGE"].removeprefix("ghcr.io/")
    credentials = f"{os.environ['REGISTRY_USER']}:{os.environ['REGISTRY_PASSWORD']}".encode()
    query = urllib.parse.urlencode({"service": "ghcr.io", "scope": f"repository:{image}:pull,push"})
    request = urllib.request.Request(
        "https://ghcr.io/token?" + query,
        headers={
            "Authorization": "Basic " + base64.b64encode(credentials).decode(),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        token = json.load(response)["token"]
    for tag in os.environ["IMMUTABLE_TAGS"].split(","):
        request = urllib.request.Request(
            f"https://ghcr.io/v2/{image}/manifests/{tag}",
            method="HEAD",
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.oci.image.index.v1+json,"
                "application/vnd.docker.distribution.manifest.list.v2+json,"
                "application/vnd.oci.image.manifest.v1+json,"
                "application/vnd.docker.distribution.manifest.v2+json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30):
                pass
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise RuntimeError(f"Registry tag check failed with HTTP {error.code}") from None
        raise RuntimeError(f"Immutable tag already exists: {tag}")


if __name__ == "__main__":
    main()
