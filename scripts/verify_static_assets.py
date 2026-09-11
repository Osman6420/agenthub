from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
REQUIRED_ASSETS = (
    Path("builder/builder.js"),
    Path("builder/builder.css"),
)
FORBIDDEN_SUFFIXES = {
    ".env",
    ".map",
    ".pem",
    ".py",
    ".pyc",
    ".pyo",
    ".sqlite3",
}
FORBIDDEN_NAME_PARTS = (
    "credentials",
    "private-key",
    "secret",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_static_tree(root: Path, release_id: str) -> dict[str, object]:
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise ValueError("release id must match [A-Za-z0-9._-]{1,128}")
    if not root.is_dir():
        raise ValueError(f"static root does not exist: {root}")

    for relative_path in REQUIRED_ASSETS:
        asset = root / relative_path
        if not asset.is_file() or asset.stat().st_size <= 0:
            raise ValueError(
                f"required static asset is missing or empty: {relative_path.as_posix()}"
            )

    assets: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symbolic links are not allowed: {path.relative_to(root).as_posix()}")
        if not path.is_file():
            continue

        relative_path = path.relative_to(root)
        relative_text = relative_path.as_posix()
        lower_name = path.name.lower()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or any(
            part in lower_name for part in FORBIDDEN_NAME_PARTS
        ):
            raise ValueError(f"forbidden static artifact: {relative_text}")
        if any(part.startswith(".") for part in relative_path.parts):
            raise ValueError(f"hidden static artifact is not allowed: {relative_text}")

        assets.append(
            {
                "path": relative_text,
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
        )

    if not assets:
        raise ValueError("static tree is empty")

    return {
        "release_id": release_id,
        "asset_count": len(assets),
        "assets": assets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify and inventory collected static assets.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    try:
        manifest = verify_static_tree(args.root.resolve(), args.release_id)
    except ValueError as exc:
        print(f"static asset verification failed: {exc}", file=sys.stderr)
        return 1

    if args.manifest:
        manifest_path = args.manifest.resolve()
        if manifest_path.parent != args.root.resolve():
            print(
                "static asset verification failed: manifest must be inside static root",
                file=sys.stderr,
            )
            return 1
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(f"verified {manifest['asset_count']} static assets for release {manifest['release_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
