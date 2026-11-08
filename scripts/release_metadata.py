import os


def main():
    image = "ghcr.io/" + os.environ["GITHUB_REPOSITORY"].lower()
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"image={image}\n")
        output.write(f"tag={image}:latest\n")


if __name__ == "__main__":
    main()
