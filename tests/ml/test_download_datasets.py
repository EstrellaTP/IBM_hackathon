import hashlib
import io
import zipfile

import pytest

from ml.data import download_datasets as dl

PAYLOAD = b"synthetic dataset bytes " * 100


def _remote(**overrides):
    fields = {
        "url": "https://example.org/file.bin",
        "target": "demo/file.bin",
        "size_bytes": len(PAYLOAD),
        "checksum": "sha256:" + hashlib.sha256(PAYLOAD).hexdigest(),
    }
    fields.update(overrides)
    return dl.RemoteFile(**fields)


class _FakeResponse(io.BytesIO):
    def __init__(self, data, status):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_verify_accepts_matching_size_and_checksum(tmp_path):
    path = tmp_path / "file.bin"
    path.write_bytes(PAYLOAD)
    dl.verify(path, _remote())


def test_verify_rejects_wrong_checksum(tmp_path):
    path = tmp_path / "file.bin"
    path.write_bytes(PAYLOAD)
    with pytest.raises(dl.DownloadError, match="sha256"):
        dl.verify(path, _remote(checksum="sha256:" + "0" * 64))


def test_verify_rejects_truncated_file(tmp_path):
    path = tmp_path / "file.bin"
    path.write_bytes(PAYLOAD[:-1])
    with pytest.raises(dl.DownloadError, match="size"):
        dl.verify(path, _remote())


def test_stream_download_resumes_from_partial_file(tmp_path, monkeypatch):
    destination = tmp_path / "file.bin"
    half = len(PAYLOAD) // 2
    (tmp_path / "file.bin.part").write_bytes(PAYLOAD[:half])
    seen = {}

    def fake_urlopen(request, timeout):
        seen["range"] = request.get_header("Range")
        return _FakeResponse(PAYLOAD[half:], status=206)

    monkeypatch.setattr(dl.urllib.request, "urlopen", fake_urlopen)
    dl.stream_download(_remote(), destination)
    assert seen["range"] == f"bytes={half}-"
    assert destination.read_bytes() == PAYLOAD
    assert not (tmp_path / "file.bin.part").exists()


def test_stream_download_restarts_when_server_ignores_range(tmp_path, monkeypatch):
    destination = tmp_path / "file.bin"
    (tmp_path / "file.bin.part").write_bytes(b"stale")
    monkeypatch.setattr(
        dl.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(PAYLOAD, 200)
    )
    dl.stream_download(_remote(), destination)
    assert destination.read_bytes() == PAYLOAD


def test_extract_zip_refuses_paths_outside_target(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "nope")
    with pytest.raises(dl.DownloadError, match="unsafe path"):
        dl.extract_zip(archive)
    assert not (tmp_path.parent / "escape.txt").exists()


def test_fetch_dataset_extracts_and_removes_archive(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("inner/data.csv", "t,value\n0,1\n")
    data = buffer.getvalue()
    remote = _remote(
        target="demo/demo.zip",
        size_bytes=len(data),
        checksum="md5:" + hashlib.md5(data).hexdigest(),
        extract=True,
    )
    monkeypatch.setitem(
        dl.DATASETS, "demo", dl.Dataset(description="demo", licence="none", files=(remote,))
    )
    monkeypatch.setattr(
        dl.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(data, 200)
    )
    dl.fetch_dataset("demo", tmp_path, keep_archives=False)
    assert (tmp_path / "demo" / "inner" / "data.csv").exists()
    assert not (tmp_path / "demo" / "demo.zip").exists()
    # A second run is a no-op thanks to the extraction marker.
    dl.fetch_dataset("demo", tmp_path, keep_archives=False)


def test_manual_dataset_missing_file_explains_how_to_get_it(tmp_path):
    with pytest.raises(dl.DownloadError, match="Dryad blocks scripted downloads"):
        dl.fetch_dataset("nurses", tmp_path, keep_archives=False)


def test_main_rejects_unknown_dataset(tmp_path):
    assert dl.main(["not-a-dataset", "--data-dir", str(tmp_path)]) == 2
