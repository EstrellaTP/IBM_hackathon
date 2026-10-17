"""Download the public datasets used by the project into ``ml/data/raw/``.

Health data lives on the LinuxONE VM, so this script is meant to run **on the VM**
(CLAUDE.md §7, task F0-ML-01). Nothing it downloads is committed: ``ml/data/raw/`` is
gitignored.

Usage (from the repository root)::

    python3 -m ml.data.download_datasets --list
    python3 -m ml.data.download_datasets wesad depresjon nhanes_h
    python3 -m ml.data.download_datasets nhanes_h_minute --keep-archives

Downloads resume after an interruption (HTTP ``Range``), are checked against the
size published by the source and, when the source publishes one, a checksum. Zip
archives are extracted next to the archive and deleted afterwards unless
``--keep-archives`` is given.

Only the Python standard library is used, so the script runs before the scientific
stack is installed.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Default target directory; override with HOLTER_DATA_DIR (12-factor configuration).
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "raw"

# Read/write block size for streaming downloads and hashing (8 MiB).
CHUNK_BYTES = 8 * 1024 * 1024

# Log download progress every this many bytes (256 MiB).
PROGRESS_EVERY_BYTES = 256 * 1024 * 1024

# Seconds without data before a connection is considered dead.
SOCKET_TIMEOUT_SECONDS = 60

# Some hosts reject clients without a browser-like User-Agent.
USER_AGENT = "Mozilla/5.0 (compatible; GigaFly-datathon-downloader/1.0)"

NHANES_BASE = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public"
NHANES_LARGE = "https://ftp.cdc.gov/pub/NHANES/LargeDataFiles"


@dataclass(frozen=True)
class RemoteFile:
    """A file published by a dataset provider.

    Attributes:
        url: Direct download URL.
        target: Path relative to the data directory.
        size_bytes: Size published by the source (Content-Length), used to verify.
        checksum: ``"<algorithm>:<hex digest>"`` when the source publishes one.
        extract: Whether the file is a zip archive to extract after download.
    """

    url: str
    target: str
    size_bytes: int
    checksum: str | None = None
    extract: bool = False


@dataclass(frozen=True)
class Dataset:
    """A dataset: its files, licence and how it is obtained.

    Attributes:
        description: One-line description for ``--list``.
        licence: Licence or terms of use, to be cited in ATTRIBUTIONS.md.
        files: Files to download.
        manual_instructions: Set when the provider blocks scripted downloads; the
            script then only verifies files a person has placed in the data directory.
    """

    description: str
    licence: str
    files: tuple[RemoteFile, ...]
    manual_instructions: str | None = None


def _nhanes(cycle_year: int, name: str, size_bytes: int, large: bool = False) -> RemoteFile:
    """Build the RemoteFile of an NHANES SAS transport (.xpt) table."""
    folder = f"nhanes/{cycle_year}"
    if large:
        url = f"{NHANES_LARGE}/{name}.xpt"
    else:
        url = f"{NHANES_BASE}/{cycle_year}/DataFiles/{name}.xpt"
    return RemoteFile(url=url, target=f"{folder}/{name}.xpt", size_bytes=size_bytes)


# Sizes and checksums were read from each provider on 2026-10-18 (HTTP HEAD, Zenodo
# and Dryad APIs). A mismatch means the provider changed the file: check before use.
DATASETS: dict[str, Dataset] = {
    "wesad": Dataset(
        description="WESAD: wrist (Empatica E4) and chest raw signals, 15 subjects, "
        "baseline/stress/amusement labels (Schmidt et al., ICMI 2018)",
        licence="Non-commercial scientific use, citing the paper (University of Siegen)",
        files=(
            RemoteFile(
                url="https://uni-siegen.sciebo.de/s/HGdUkoNlW1Ub0Gx/download",
                target="wesad/WESAD.zip",
                size_bytes=2_249_444_501,
                extract=True,
            ),
        ),
    ),
    "depresjon": Dataset(
        description="DEPRESJON: minute-level actigraphy of 23 patients and 32 controls "
        "with MADRS scores (Garcia-Ceja et al., MMSys 2018)",
        licence="CC BY-NC 4.0 (Zenodo record 1219550), cite the paper",
        files=(
            RemoteFile(
                url="https://zenodo.org/api/records/1219550/files/depresjon-dataset.zip/content",
                target="depresjon/depresjon-dataset.zip",
                size_bytes=4_266_305,
                checksum="md5:6c96ed5ec92ef551b2db1c7f1276809d",
                extract=True,
            ),
        ),
    ),
    "nhanes_h": Dataset(
        description="NHANES 2013-2014 (cycle H): demographics, PHQ-9, accelerometer "
        "header, hourly and daily summaries (MIMS)",
        licence="Public domain (US CDC/NCHS)",
        files=(
            _nhanes(2013, "DEMO_H", 3_833_200),
            _nhanes(2013, "DPQ_H", 523_680),
            _nhanes(2013, "PAXHD_H", 438_800),
            _nhanes(2013, "PAXDAY_H", 7_318_800),
            _nhanes(2013, "PAXHR_H", 144_753_200),
        ),
    ),
    "nhanes_h_minute": Dataset(
        description="NHANES 2013-2014 minute-level accelerometry PAXMIN_H (8.7 GiB)",
        licence="Public domain (US CDC/NCHS)",
        files=(_nhanes(2013, "PAXMIN_H", 9_351_691_760, large=True),),
    ),
    "nhanes_g": Dataset(
        description="NHANES 2011-2012 (cycle G): demographics and PHQ-9",
        licence="Public domain (US CDC/NCHS)",
        files=(
            _nhanes(2011, "DEMO_G", 3_753_760),
            _nhanes(2011, "DPQ_G", 496_480),
        ),
    ),
    "nhanes_g_minute": Dataset(
        description="NHANES 2011-2012 minute-level accelerometry PAXMIN_G (7.6 GiB)",
        licence="Public domain (US CDC/NCHS)",
        files=(_nhanes(2011, "PAXMIN_G", 8_125_196_000, large=True),),
    ),
    "nurses": Dataset(
        description="Nurse stress in a hospital: Empatica E4 signals of 15 nurses with "
        "confirmed stress events (Hosseini et al., Sci Data 2022)",
        licence="CC0 1.0 (Dryad doi:10.5061/dryad.5hqbzkh6f)",
        files=(
            RemoteFile(
                url="https://datadryad.org/dataset/doi:10.5061/dryad.5hqbzkh6f",
                target="nurses/Stress_dataset.zip",
                size_bytes=1_156_939_542,
                checksum="sha256:86e7146cbb124f9b5e37bc5bd8fa63f8786379dfdb10dfc9fdc5fd6c41e63407",
                extract=True,
            ),
            RemoteFile(
                url="https://datadryad.org/dataset/doi:10.5061/dryad.5hqbzkh6f",
                target="nurses/SurveyResults.xlsx",
                size_bytes=49_048,
                checksum="sha256:4ee7733f8e8da362af33a765c495f4a5ed8302b5af39327c2cdb420a27def2b3",
            ),
        ),
        # Dryad answers 401 to its API and 403 to non-browser downloads.
        manual_instructions=(
            "Dryad blocks scripted downloads. Download Stress_dataset.zip and "
            "SurveyResults.xlsx in a browser from "
            "https://datadryad.org/dataset/doi:10.5061/dryad.5hqbzkh6f and copy them "
            "to <data dir>/nurses/ on the VM, e.g. "
            "scp Stress_dataset.zip SurveyResults.xlsx l1cc:IBM_hackathon/ml/data/raw/nurses/ "
            "then run this script again to verify and extract them."
        ),
    ),
}


class DownloadError(RuntimeError):
    """A file could not be downloaded or failed verification."""


def file_digest(path: Path, algorithm: str) -> str:
    """Return the hex digest of a file, read in chunks.

    Args:
        path: File to hash.
        algorithm: Name accepted by :func:`hashlib.new` (``md5``, ``sha256``...).

    Returns:
        Lower-case hex digest.
    """
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while block := handle.read(CHUNK_BYTES):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path, remote: RemoteFile) -> None:
    """Check size and checksum of a downloaded file.

    Args:
        path: Local file.
        remote: Expected properties.

    Raises:
        DownloadError: If the size or the checksum does not match.
    """
    size = path.stat().st_size
    if size != remote.size_bytes:
        raise DownloadError(f"{path.name}: size {size} != expected {remote.size_bytes}")
    if remote.checksum:
        algorithm, expected = remote.checksum.split(":", 1)
        actual = file_digest(path, algorithm)
        if actual != expected:
            raise DownloadError(f"{path.name}: {algorithm} {actual} != expected {expected}")


def stream_download(remote: RemoteFile, destination: Path) -> None:
    """Download ``remote`` to ``destination``, resuming a previous partial download.

    Data is written to ``<destination>.part`` and renamed only after verification,
    so a complete-looking file is always a verified one.

    Args:
        remote: File to download.
        destination: Final local path.

    Raises:
        DownloadError: If the server fails or the result does not verify.
    """
    partial = destination.with_name(destination.name + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(remote.url, headers={"User-Agent": USER_AGENT})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
        logger.info("Resuming %s at %.1f MiB", destination.name, offset / 2**20)
    try:
        with urllib.request.urlopen(request, timeout=SOCKET_TIMEOUT_SECONDS) as response:
            # 200 means the server ignored Range: start again from the beginning.
            mode = "ab" if offset and response.status == 206 else "wb"
            written = offset if mode == "ab" else 0
            next_log = written + PROGRESS_EVERY_BYTES
            with partial.open(mode) as handle:
                while block := response.read(CHUNK_BYTES):
                    handle.write(block)
                    written += len(block)
                    if written >= next_log:
                        logger.info(
                            "%s: %.0f / %.0f MiB",
                            destination.name,
                            written / 2**20,
                            remote.size_bytes / 2**20,
                        )
                        next_log += PROGRESS_EVERY_BYTES
    except OSError as error:  # URLError and socket timeouts are OSError subclasses.
        raise DownloadError(f"{remote.url}: {error}") from error
    verify(partial, remote)
    partial.replace(destination)


def extract_zip(archive: Path) -> None:
    """Extract a zip archive into its own directory, refusing unsafe member paths.

    Args:
        archive: Zip file to extract.

    Raises:
        DownloadError: If a member would be written outside the target directory.
    """
    target = archive.parent.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            if not (target / member).resolve().is_relative_to(target):
                raise DownloadError(f"{archive.name}: unsafe path {member!r} in archive")
        bundle.extractall(target)
    logger.info("Extracted %s into %s", archive.name, target)


def fetch_dataset(name: str, data_dir: Path, keep_archives: bool) -> None:
    """Download (or verify, for manual datasets), and extract one dataset.

    Args:
        name: Key of :data:`DATASETS`.
        data_dir: Root data directory.
        keep_archives: Keep zip files after extraction.

    Raises:
        DownloadError: If a file cannot be obtained or verified.
    """
    dataset = DATASETS[name]
    for remote in dataset.files:
        destination = data_dir / remote.target
        destination.parent.mkdir(parents=True, exist_ok=True)
        marker = destination.with_name(destination.name + ".extracted")
        if marker.exists():
            logger.info("%s: already downloaded and extracted", remote.target)
            continue
        if destination.exists():
            verify(destination, remote)
            logger.info("%s: present and verified", remote.target)
        elif dataset.manual_instructions:
            raise DownloadError(f"{remote.target} is missing. {dataset.manual_instructions}")
        else:
            logger.info("Downloading %s (%.1f MiB)", remote.target, remote.size_bytes / 2**20)
            stream_download(remote, destination)
            logger.info("%s: downloaded and verified", remote.target)
        if remote.extract:
            extract_zip(destination)
            marker.touch()
            if not keep_archives:
                destination.unlink()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("datasets", nargs="*", metavar="DATASET", help="names from --list")
    parser.add_argument("--list", action="store_true", help="list datasets and exit")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("HOLTER_DATA_DIR", DEFAULT_DATA_DIR)),
        help="target directory (default: $HOLTER_DATA_DIR or ml/data/raw)",
    )
    parser.add_argument(
        "--keep-archives", action="store_true", help="keep zip files after extraction"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the downloader; return a process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    if args.list or not args.datasets:
        for name, dataset in DATASETS.items():
            total = sum(remote.size_bytes for remote in dataset.files) / 2**20
            manual = " [manual download]" if dataset.manual_instructions else ""
            logger.info("%-16s %9.1f MiB  %s%s", name, total, dataset.description, manual)
        return 0
    unknown = sorted(set(args.datasets) - set(DATASETS))
    if unknown:
        logger.error("Unknown dataset(s): %s. Use --list.", ", ".join(unknown))
        return 2
    existing = args.data_dir if args.data_dir.exists() else args.data_dir.parent
    free_bytes = shutil.disk_usage(existing).free
    logger.info("Data dir %s, %.1f GiB free", args.data_dir, free_bytes / 2**30)
    failures = 0
    for name in args.datasets:
        try:
            fetch_dataset(name, args.data_dir, args.keep_archives)
        except DownloadError as error:
            logger.error("%s: %s", name, error)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
