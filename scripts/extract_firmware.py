#!/usr/bin/env python3
import argparse
import gzip
import json
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path


SQUASHFS_MAGICS = (b"hsqs", b"sqsh", b"qshs", b"shsq")
GZIP_MAGIC = b"\x1f\x8b\x08"


def run(cmd, check=True):
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def safe_extract_zip(path, dest):
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            target = dest / member.filename
            resolved = target.resolve()
            if not str(resolved).startswith(str(dest.resolve())):
                raise RuntimeError(f"blocked unsafe zip path: {member.filename}")
            archive.extract(member, dest)


def safe_extract_tar(path, dest):
    with tarfile.open(path) as archive:
        for member in archive.getmembers():
            target = dest / member.name
            resolved = target.resolve()
            if not str(resolved).startswith(str(dest.resolve())):
                raise RuntimeError(f"blocked unsafe tar path: {member.name}")
            archive.extract(member, dest)


def find_offsets(path, magic):
    offsets = []
    with path.open("rb") as handle:
        base = 0
        overlap = b""
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            data = overlap + chunk
            start = 0
            while True:
                index = data.find(magic, start)
                if index < 0:
                    break
                offsets.append(base - len(overlap) + index)
                start = index + 1
            overlap = data[-(len(magic) - 1) :]
            base += len(chunk)
    return offsets


def decompress_gzip_member(path, offset, dest):
    with path.open("rb") as raw:
        raw.seek(offset)
        with gzip.GzipFile(fileobj=raw) as gz, dest.open("wb") as out:
            shutil.copyfileobj(gz, out)


def find_candidate_files(root):
    suffixes = {".bin", ".img", ".trx", ".chk", ".raw", ".gz", ".tar", ".squashfs"}
    files = [path for path in root.rglob("*") if path.is_file()]
    return sorted(
        [path for path in files if path.suffix.lower() in suffixes],
        key=lambda path: path.stat().st_size,
        reverse=True,
    )


def unsquashfs(image, dest, offset=0):
    if dest.exists():
        shutil.rmtree(dest)
    cmd = [
        "unsquashfs",
        "-ignore-errors",
        "-no-exit-code",
        "-d",
        str(dest),
    ]
    if offset:
        cmd.extend(["-o", str(offset)])
    cmd.append(str(image))
    result = run(cmd, check=False)
    return dest.exists() and any(dest.iterdir()), result.stdout + result.stderr


def extract_nested(candidate, workdir):
    outputs = []
    if candidate.suffix.lower() == ".gz" or find_offsets(candidate, GZIP_MAGIC):
        for index, offset in enumerate(find_offsets(candidate, GZIP_MAGIC)[:4]):
            out = workdir / f"{candidate.stem}.gzip{index}.raw"
            try:
                decompress_gzip_member(candidate, offset, out)
                outputs.append(out)
            except Exception:
                pass
    if tarfile.is_tarfile(candidate):
        out_dir = workdir / f"{candidate.stem}.tar"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_extract_tar(candidate, out_dir)
        outputs.append(out_dir)
    return outputs


def detect_arch(rootfs):
    candidates = [
        rootfs / "bin/busybox",
        rootfs / "bin/sh",
        rootfs / "sbin/init",
    ]
    candidates.extend(path for path in (rootfs / "usr/bin").glob("*") if path.is_file())
    for path in candidates:
        if not path.exists() or path.is_symlink():
            continue
        result = run(["file", str(path)], check=False).stdout
        if "ARM aarch64" in result:
            return "aarch64", result.strip()
        if "ARM," in result or "ARM EABI" in result:
            return "arm", result.strip()
        if "MIPS" in result:
            if "LSB" in result:
                return "mipsel", result.strip()
            return "mips", result.strip()
        if "Intel 80386" in result:
            return "i386", result.strip()
        if "x86-64" in result:
            return "x86_64", result.strip()
    return "unknown", ""


def extract_archive(archive, workdir):
    archive = archive.resolve()
    workdir = workdir.resolve()
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    initial = workdir / "initial"
    initial.mkdir()
    if zipfile.is_zipfile(archive):
        safe_extract_zip(archive, initial)
    elif tarfile.is_tarfile(archive):
        safe_extract_tar(archive, initial)
    else:
        shutil.copy2(archive, initial / archive.name)

    scan_roots = [initial]
    for round_index in range(4):
        new_outputs = []
        for root in list(scan_roots):
            for candidate in find_candidate_files(root):
                if candidate.name.endswith(".squashfs"):
                    continue
                nested_dir = workdir / "nested" / f"round{round_index}"
                nested_dir.mkdir(parents=True, exist_ok=True)
                new_outputs.extend(extract_nested(candidate, nested_dir))
        if not new_outputs:
            break
        scan_roots.extend(path for path in new_outputs if path.is_dir())
        for path in new_outputs:
            if path.is_file() and tarfile.is_tarfile(path):
                out_dir = path.with_suffix(path.suffix + ".tar")
                out_dir.mkdir(parents=True, exist_ok=True)
                safe_extract_tar(path, out_dir)
                scan_roots.append(out_dir)

    squashfs_candidates = []
    for root in scan_roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name.endswith(".squashfs"):
                squashfs_candidates.append((path, 0))
                continue
            for magic in SQUASHFS_MAGICS:
                for offset in find_offsets(path, magic)[:4]:
                    squashfs_candidates.append((path, offset))

    tried = []
    for index, (image, offset) in enumerate(squashfs_candidates):
        rootfs = workdir / f"rootfs_{index}"
        ok, log = unsquashfs(image, rootfs, offset)
        tried.append({"image": str(image), "offset": offset, "ok": ok, "logTail": log[-2000:]})
        if ok:
            arch, arch_detail = detect_arch(rootfs)
            return {
                "archive": str(archive),
                "workdir": str(workdir),
                "rootfs": str(rootfs),
                "arch": arch,
                "archDetail": arch_detail,
                "squashfsImage": str(image),
                "squashfsOffset": offset,
                "attempts": tried,
            }

    binwalk_dir = workdir / "binwalk"
    binwalk_dir.mkdir(exist_ok=True)
    run(["binwalk", "-Me", "-C", str(binwalk_dir), str(archive)], check=False)
    for path in binwalk_dir.rglob("squashfs-root"):
        if path.is_dir():
            arch, arch_detail = detect_arch(path)
            return {
                "archive": str(archive),
                "workdir": str(workdir),
                "rootfs": str(path),
                "arch": arch,
                "archDetail": arch_detail,
                "squashfsImage": None,
                "squashfsOffset": None,
                "attempts": tried,
            }

    raise RuntimeError("could not extract a root filesystem")


def main():
    parser = argparse.ArgumentParser(description="Extract a Tenda firmware archive to a runnable rootfs.")
    parser.add_argument("archive")
    parser.add_argument("--workdir", default="/work/extracted/current")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = extract_archive(Path(args.archive), Path(args.workdir))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["rootfs"])


if __name__ == "__main__":
    main()
