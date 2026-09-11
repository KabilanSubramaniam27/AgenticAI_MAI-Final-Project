import pytest

from tripradar_ingestion.config import Settings
from tripradar_ingestion.manifest import Manifest
from tripradar_ingestion.registry import load_registry, resolve_destination
from tripradar_ingestion.utils import writer_lock


def test_old_provider_env_does_not_override_local_model(root_settings, monkeypatch):
    (root_settings.root / ".env").write_text("EMBEDDING_DIMENSION=4096\nNEBIUS_API_KEY=ignored\n")
    monkeypatch.delenv("TRIPRADAR_EMBEDDING_DIMENSION", raising=False)
    assert Settings.load(root_settings.root).embedding_dimension == 384
    assert resolve_destination(load_registry(root_settings.root), "New york").id == "new_york_city"


def test_artifact_tampering_invalidates_checkpoint(settings):
    path = settings.root / "artifact"
    path.write_text("valid")
    manifest = Manifest(settings.data)
    manifest.record("lisbon", "parse", "v1", path)
    assert manifest.cached("lisbon", "parse", "v1") == path
    path.write_text("modified")
    assert manifest.cached("lisbon", "parse", "v1") is None
    manifest.close()


def test_single_writer(settings):
    with writer_lock(settings.data), pytest.raises(RuntimeError, match="writer"):
        with writer_lock(settings.data):
            pass


def test_documented_environment_values_load(root_settings, monkeypatch):
    from pathlib import Path

    sample = Path(__file__).resolve().parents[2] / ".env.example"
    (root_settings.root / ".env").write_text(sample.read_text())
    monkeypatch.setenv("TRIPRADAR_ROOT", str(root_settings.root))
    assert Settings.load().embedding_dimension == 384
    monkeypatch.setenv("TRIPRADAR_EMBEDDING_DIMENSION", "4096")
    with pytest.raises(ValueError):
        Settings.load()
