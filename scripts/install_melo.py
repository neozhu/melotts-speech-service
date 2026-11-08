"""Install the pinned official source, adding only HF revision keywords.

Upstream setup.py downloads a full Japanese dictionary in its install hook.
Copying the official package avoids that hook and its unrelated training/UI
dependencies. All inference and phonemization algorithms remain upstream code.
"""

import ast
import hashlib
import io
import pickle
import shutil
import sysconfig
import tarfile
import tempfile
import urllib.request
from pathlib import Path

COMMIT = "209145371cff8fc3bd60d7be902ea69cbdb7965a"
SHA256 = "ceb9a1a636522fee6489c8496ef5b6b9b3b8c1e8441f402eea00d8a17fbe52b8"


class PinFrontends(ast.NodeTransformer):
    def __init__(self):
        self.count = 0

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "from_pretrained":
            node.keywords.append(
                ast.keyword(
                    arg=None,
                    value=ast.Call(
                        func=ast.Name(id="pretrained_options", ctx=ast.Load()),
                        args=[node.args[0]],
                        keywords=[],
                    ),
                )
            )
            self.count += 1
        return node


def prepare_package(package: Path):
    patched = 0
    for path in (package / "text").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        transformer = PinFrontends()
        tree = transformer.visit(tree)
        if transformer.count:
            source = (
                "from app.services.model_assets import pretrained_options\n"
                + ast.unparse(ast.fix_missing_locations(tree))
                + "\n"
            )
            path.write_text(source, encoding="utf-8")
            patched += transformer.count
    if patched != 16:
        raise RuntimeError(f"Upstream frontend calls changed: expected 16, found {patched}")

    # Upstream writes this cache next to english.py on import. Generate it at build
    # time so runtime can use a read-only root filesystem.
    tree = ast.parse((package / "text/english.py").read_text(encoding="utf-8"))
    read_dict = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "read_dict"
    )
    namespace = {"CMU_DICT_PATH": str(package / "text/cmudict.rep")}
    exec(compile(ast.Module(body=[read_dict], type_ignores=[]), "read_dict", "exec"), namespace)
    with (package / "text/cmudict_cache.pickle").open("wb") as cache:
        pickle.dump(namespace["read_dict"](), cache)


def main():
    url = f"https://codeload.github.com/myshell-ai/MeloTTS/tar.gz/{COMMIT}"
    with urllib.request.urlopen(url, timeout=120) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != SHA256:
        raise RuntimeError("MeloTTS source checksum mismatch")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
            # Only regular files under this exact verified prefix; never extract links.
            prefix = f"MeloTTS-{COMMIT}/"
            for member in source.getmembers():
                if not member.isfile() or not member.name.startswith(prefix):
                    continue
                relative = Path(member.name[len(prefix) :])
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError("Unsafe source archive")
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as content:
                    target.write_bytes(content.read())
        prepare_package(root / "melo")
        destination = Path(sysconfig.get_paths()["purelib"]) / "melo"
        shutil.copytree(root / "melo", destination)
        shutil.copy2(root / "LICENSE", destination / "LICENSE")
        (destination / "UPSTREAM_COMMIT").write_text(COMMIT + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
