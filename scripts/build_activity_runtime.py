#!/usr/bin/env python3
"""Patch one Python module in an existing PyInstaller EXO executable.

The script preserves every other PYZ code object and CArchive entry byte for
byte, then appends the rebuilt archive to a supplied PyInstaller bootloader.
Run it with the same Python minor version as the target EXO runtime.
"""

from __future__ import annotations

import argparse
import importlib.util
import marshal
import struct
import zlib
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
from PyInstaller.archive.writers import CArchiveWriter
from PyInstaller.building.utils import replace_filename_in_code_object
from PyInstaller.utils import osx


def rebuild_pyz(original_pyz: Path, source_main: Path, output_pyz: Path) -> None:
    reader = ZlibArchiveReader(str(original_pyz), check_pymagic=True)
    replacement = compile(
        source_main.read_text(encoding="utf-8"),
        "exo/api/main.py",
        "exec",
        optimize=0,
    )
    replacement = replace_filename_in_code_object(replacement, "exo/api/main.py")
    replacement_blob = zlib.compress(marshal.dumps(replacement), level=6)

    entries: list[tuple[str, tuple[int, int, int]]] = []
    with original_pyz.open("rb") as source, output_pyz.open("wb") as target:
        original_header = source.read(17)
        target.write(original_header)

        for name, (typecode, offset, length) in reader.toc.items():
            new_offset = target.tell()
            if name == "exo.api.main":
                blob = replacement_blob
            else:
                source.seek(offset)
                blob = source.read(length)
            target.write(blob)
            entries.append((name, (typecode, new_offset, len(blob))))

        toc_offset = target.tell()
        marshal.dump(entries, target)
        target.seek(0)
        target.write(b"PYZ\0")
        target.write(importlib.util.MAGIC_NUMBER)
        target.write(struct.pack("!i", toc_offset))


def rebuild_executable(
    base_executable: Path,
    replacement_pyz: Path,
    bootloader: Path,
    output_executable: Path,
) -> None:
    reader = CArchiveReader(str(base_executable))
    with base_executable.open("rb") as source:
        source.seek(reader._end_offset - reader._COOKIE_LENGTH)  # noqa: SLF001
        cookie = source.read(reader._COOKIE_LENGTH)  # noqa: SLF001
        _, _, _, _, python_version, python_library = struct.unpack(
            reader._COOKIE_FORMAT, cookie  # noqa: SLF001
        )

        archive = bytearray()
        toc: list[tuple[int, int, int, int, str, str]] = []
        for option in reader.options:
            toc.append((len(archive), 0, 0, 0, "o", option))

        for name, (
            offset,
            compressed_length,
            uncompressed_length,
            compressed,
            typecode,
        ) in reader.toc.items():
            data_offset = len(archive)
            if name == "PYZ.pyz":
                blob = replacement_pyz.read_bytes()
                compressed_length = len(blob)
                uncompressed_length = len(blob)
                compressed = 0
            else:
                source.seek(reader._start_offset + offset)  # noqa: SLF001
                blob = source.read(compressed_length)
            archive.extend(blob)
            toc.append(
                (
                    data_offset,
                    compressed_length,
                    uncompressed_length,
                    compressed,
                    typecode,
                    name,
                )
            )

    toc_offset = len(archive)
    toc_blob = CArchiveWriter._serialize_toc(toc)  # noqa: SLF001
    archive.extend(toc_blob)
    archive_length = len(archive) + reader._COOKIE_LENGTH  # noqa: SLF001
    archive.extend(
        struct.pack(
            reader._COOKIE_FORMAT,  # noqa: SLF001
            reader._COOKIE_MAGIC_PATTERN,  # noqa: SLF001
            archive_length,
            toc_offset,
            len(toc_blob),
            python_version,
            python_library,
        )
    )

    output_executable.write_bytes(bootloader.read_bytes() + archive)
    osx.fix_exe_for_code_signing(str(output_executable))
    output_executable.chmod(0o755)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-executable", type=Path, required=True)
    parser.add_argument("--source-main", type=Path, required=True)
    parser.add_argument("--bootloader", type=Path, required=True)
    parser.add_argument("--output-executable", type=Path, required=True)
    parser.add_argument("--output-pyz", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_executable.parent.mkdir(parents=True, exist_ok=True)
    args.output_pyz.parent.mkdir(parents=True, exist_ok=True)

    base_reader = CArchiveReader(str(args.base_executable))
    original_pyz = args.output_pyz.with_suffix(".original.pyz")
    original_pyz.write_bytes(base_reader.extract("PYZ.pyz"))
    try:
        rebuild_pyz(original_pyz, args.source_main, args.output_pyz)
        rebuild_executable(
            args.base_executable,
            args.output_pyz,
            args.bootloader,
            args.output_executable,
        )
    finally:
        original_pyz.unlink(missing_ok=True)

    print(f"wrote {args.output_executable}")
    print(f"wrote {args.output_pyz}")


if __name__ == "__main__":
    main()
