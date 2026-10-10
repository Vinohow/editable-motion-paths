from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = ROOT / "extension"
DIST_DIR = ROOT / "dist"
MANIFEST_PATH = EXTENSION_DIR / "blender_manifest.toml"
REQUIRED_EXTENSION_FILES = ("__init__.py", "blender_manifest.toml")


def read_manifest() -> dict[str, object]:
    try:
        with MANIFEST_PATH.open("rb") as manifest_file:
            manifest = tomllib.load(manifest_file)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing extension manifest: {MANIFEST_PATH}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"Invalid TOML in {MANIFEST_PATH}: {exc}") from exc

    for field in ("id", "version"):
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Manifest field '{field}' must be a non-empty string")
    return manifest


def validate_extension_tree() -> None:
    missing = [name for name in REQUIRED_EXTENSION_FILES if not (EXTENSION_DIR / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing required extension file(s): {', '.join(missing)}")


def build_extension() -> Path:
    validate_extension_tree()
    manifest = read_manifest()
    addon_id = str(manifest["id"])
    version = str(manifest["version"])

    DIST_DIR.mkdir(exist_ok=True)
    archive_path = DIST_DIR / f"{addon_id}-{version}.zip"
    archive_path.unlink(missing_ok=True)

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source_path in sorted(EXTENSION_DIR.rglob("*")):
            if not source_path.is_file():
                continue
            relative_path = source_path.relative_to(EXTENSION_DIR)
            if "__pycache__" in relative_path.parts or source_path.suffix in {".pyc", ".pyo"}:
                continue
            archive.write(source_path, relative_path.as_posix())

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        missing = [name for name in REQUIRED_EXTENSION_FILES if name not in names]
        if missing:
            archive_path.unlink(missing_ok=True)
            raise RuntimeError(f"Built archive is missing: {', '.join(missing)}")
        if archive.testzip() is not None:
            archive_path.unlink(missing_ok=True)
            raise RuntimeError("Built archive failed ZIP integrity validation")

    return archive_path


def main() -> int:
    try:
        archive_path = build_extension()
    except (OSError, RuntimeError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1

    print(archive_path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
