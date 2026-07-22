"""Verify that Minerva's built artifacts contain the required package resources."""

from __future__ import annotations

import argparse
import configparser
import email.parser
import sys
import tarfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

EXPECTED_DISTRIBUTION = "minerva-research"
EXPECTED_ENTRY_POINTS = {
    "minerva": "minerva.cli.main:main",
    "minerva-demo": "minerva.cli.demo:main",
}

EXPECTED_RESOURCES = frozenset(
    PurePosixPath(name)
    for name in (
        "minerva/py.typed",
        "minerva/core/migrations/0001_research_core.sql",
        "minerva/core/migrations/0002_findings_and_exports.sql",
        "minerva/web/templates/base.html",
        "minerva/web/templates/brief_preview.html",
        "minerva/web/templates/claim_detail.html",
        "minerva/web/templates/mission_detail.html",
        "minerva/web/templates/missions.html",
        "minerva/web/static/style.css",
    )
)
RESOURCE_PARENTS = (
    "minerva/core/migrations",
    "minerva/web/templates",
    "minerva/web/static",
)


class VerificationError(RuntimeError):
    """Raised when a distribution artifact violates the packaging contract."""


def _under(path: PurePosixPath, parent: str) -> bool:
    parent_path = PurePosixPath(parent)
    return len(path.parts) > len(parent_path.parts) and path.parts[: len(parent_path.parts)] == (
        parent_path.parts
    )


def _validated_member_path(raw_name: str, artifact: Path) -> PurePosixPath:
    path = PurePosixPath(raw_name)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise VerificationError(f"{artifact.name} contains unsafe member path {raw_name!r}")
    return path


def _packaged_resources(names: set[PurePosixPath]) -> set[PurePosixPath]:
    return {
        name
        for name in names
        if name == PurePosixPath("minerva/py.typed")
        or (_under(name, "minerva/core/migrations") and name.suffix == ".sql")
        or (_under(name, "minerva/web/templates") and name.suffix == ".html")
        or _under(name, "minerva/web/static")
    }


def _require_exact_resources(names: set[PurePosixPath], artifact: Path) -> None:
    actual = _packaged_resources(names)
    missing = sorted(EXPECTED_RESOURCES - actual, key=str)
    unexpected = sorted(actual - EXPECTED_RESOURCES, key=str)
    if missing:
        detail = ", ".join(str(path) for path in missing)
        raise VerificationError(f"{artifact.name} is missing required package resources: {detail}")
    if unexpected:
        detail = ", ".join(str(path) for path in unexpected)
        raise VerificationError(f"{artifact.name} has unmanifested package resources: {detail}")


def _parse_metadata(raw_metadata: bytes, artifact: Path) -> tuple[str, str]:
    try:
        metadata = email.parser.BytesParser().parsebytes(raw_metadata)
    except (TypeError, UnicodeError) as exc:
        raise VerificationError(f"{artifact.name} contains unreadable package metadata") from exc

    name = metadata.get("Name", "").strip()
    version = metadata.get("Version", "").strip()
    if name != EXPECTED_DISTRIBUTION:
        raise VerificationError(
            f"{artifact.name} metadata names {name!r}, expected {EXPECTED_DISTRIBUTION!r}"
        )
    if not version:
        raise VerificationError(f"{artifact.name} metadata has no Version field")
    return name, version


def _verify_entry_points(raw_entry_points: bytes, artifact: Path) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(raw_entry_points.decode("utf-8"))
    except (configparser.Error, UnicodeDecodeError) as exc:
        raise VerificationError(f"{artifact.name} has invalid entry-point metadata") from exc

    if not parser.has_section("console_scripts"):
        raise VerificationError(f"{artifact.name} has no console_scripts entry-point group")
    actual = dict(parser.items("console_scripts"))
    for command, target in EXPECTED_ENTRY_POINTS.items():
        if actual.get(command) != target:
            raise VerificationError(
                f"{artifact.name} entry point {command!r} does not resolve to {target!r}"
            )


def _verify_wheel(wheel: Path) -> tuple[tuple[str, str], set[PurePosixPath]]:
    try:
        with zipfile.ZipFile(wheel) as archive:
            file_infos = [info for info in archive.infolist() if not info.is_dir()]
            names = [_validated_member_path(info.filename, wheel) for info in file_infos]
            if len(names) != len(set(names)):
                raise VerificationError(f"{wheel.name} contains duplicate member names")
            name_set = set(names)

            metadata_paths = [
                name
                for name in name_set
                if len(name.parts) == 2
                and name.parts[0].endswith(".dist-info")
                and name.name == "METADATA"
            ]
            if len(metadata_paths) != 1:
                raise VerificationError(f"{wheel.name} must contain exactly one METADATA file")
            dist_info = metadata_paths[0].parent
            for required_name in ("WHEEL", "RECORD", "entry_points.txt"):
                required_path = dist_info / required_name
                if required_path not in name_set:
                    raise VerificationError(f"{wheel.name} is missing {required_path}")

            metadata = _parse_metadata(archive.read(str(metadata_paths[0])), wheel)
            _verify_entry_points(archive.read(str(dist_info / "entry_points.txt")), wheel)
            _require_exact_resources(name_set, wheel)
    except (OSError, zipfile.BadZipFile) as exc:
        raise VerificationError(f"unable to read wheel {wheel.name}") from exc

    return metadata, name_set


def _verify_sdist(sdist: Path) -> tuple[tuple[str, str], set[PurePosixPath]]:
    try:
        with tarfile.open(sdist, mode="r:gz") as archive:
            file_members = []
            raw_names: list[PurePosixPath] = []
            for member in archive.getmembers():
                member_path = _validated_member_path(member.name, sdist)
                if member.issym() or member.islnk():
                    raise VerificationError(f"{sdist.name} contains link member {member.name!r}")
                if member.isfile():
                    file_members.append(member)
                    raw_names.append(member_path)

            if len(raw_names) != len(set(raw_names)):
                raise VerificationError(f"{sdist.name} contains duplicate member names")
            roots = {name.parts[0] for name in raw_names}
            if len(roots) != 1:
                raise VerificationError(f"{sdist.name} must have one top-level source directory")

            root = next(iter(roots))
            relative_names = {
                PurePosixPath(*name.parts[1:]) for name in raw_names if len(name.parts) > 1
            }
            required_root_files = {PurePosixPath("README.md"), PurePosixPath("pyproject.toml")}
            missing_root_files = sorted(required_root_files - relative_names, key=str)
            if missing_root_files:
                missing = ", ".join(str(path) for path in missing_root_files)
                raise VerificationError(f"{sdist.name} is missing required source files: {missing}")

            package_names = {
                PurePosixPath(*name.parts[1:])
                for name in relative_names
                if name.parts and name.parts[0] == "src" and len(name.parts) > 1
            }
            _require_exact_resources(package_names, sdist)

            metadata_member_name = f"{root}/PKG-INFO"
            metadata_member = next(
                (member for member in file_members if member.name == metadata_member_name), None
            )
            if metadata_member is None:
                raise VerificationError(f"{sdist.name} is missing PKG-INFO")
            metadata_file = archive.extractfile(metadata_member)
            if metadata_file is None:
                raise VerificationError(f"{sdist.name} PKG-INFO is not readable")
            metadata = _parse_metadata(metadata_file.read(), sdist)
    except (OSError, tarfile.TarError) as exc:
        raise VerificationError(f"unable to read source distribution {sdist.name}") from exc

    return metadata, package_names


def verify_dist(dist_directory: Path) -> tuple[Path, Path]:
    """Verify one wheel and one sdist in *dist_directory* and return their paths."""
    dist_directory = dist_directory.resolve()
    if not dist_directory.is_dir():
        raise VerificationError(f"distribution directory does not exist: {dist_directory}")

    wheels = sorted(dist_directory.glob("*.whl"))
    sdists = sorted(dist_directory.glob("*.tar.gz"))
    if len(wheels) != 1:
        raise VerificationError(f"expected exactly one wheel, found {len(wheels)}")
    if len(sdists) != 1:
        raise VerificationError(f"expected exactly one source distribution, found {len(sdists)}")

    wheel_metadata, wheel_names = _verify_wheel(wheels[0])
    sdist_metadata, sdist_names = _verify_sdist(sdists[0])
    if wheel_metadata != sdist_metadata:
        raise VerificationError(
            "wheel and source distribution metadata disagree: "
            f"{wheel_metadata!r} != {sdist_metadata!r}"
        )

    wheel_resources = {name for name in wheel_names if name.parts and name.parts[0] == "minerva"}
    missing_from_sdist = sorted(wheel_resources - sdist_names, key=str)
    if missing_from_sdist:
        missing = ", ".join(str(path) for path in missing_from_sdist)
        raise VerificationError(f"source distribution omits wheel package files: {missing}")

    return wheels[0], sdists[0]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_directory", type=Path, help="directory containing built artifacts")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        wheel, sdist = verify_dist(args.dist_directory)
    except VerificationError as exc:
        print(f"distribution verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified wheel: {wheel.name}")
    print(f"verified source distribution: {sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
