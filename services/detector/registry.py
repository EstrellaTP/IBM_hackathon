"""Per-patient detector instances held by the detector service.

Kept apart from ``core.py`` (pure detection logic) and ``api.py`` (HTTP): this module
owns the in-memory state of the service.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from functools import lru_cache

from services.common.schemas import EpisodeEvent, SignalBatch
from services.detector.core import DetectorConfig, PatientDetector
from services.detector.settings import load_config

logger = logging.getLogger(__name__)

# Reported with every inference and written to the audit log. "zscore-2" is the
# detector after the WESAD tuning of F1-ML-02 and the safety fix of issue #6.
MODEL_VERSION = "zscore-2"


class DetectorRegistry:
    """Creates and keeps one detector per patient, thread-safe.

    Args:
        config: Configuration shared by every patient's detector.
    """

    def __init__(self, config: DetectorConfig) -> None:
        self.config = config
        self.model_version = MODEL_VERSION
        self._detectors: dict[str, PatientDetector] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()

    def _get(self, patient_id: str) -> tuple[PatientDetector, threading.Lock]:
        with self._registry_lock:
            if patient_id not in self._detectors:
                self._detectors[patient_id] = PatientDetector(patient_id, self.config)
                self._locks[patient_id] = threading.Lock()
                logger.info("patient=%s detector created", patient_id)
            return self._detectors[patient_id], self._locks[patient_id]

    def process(self, batch: SignalBatch, ingested_at: datetime | None) -> list[EpisodeEvent]:
        """Feed a batch to its patient's detector and return the episodes found."""
        detector, lock = self._get(batch.patient_id)
        with lock:
            return detector.process(batch.samples, ingested_at)

    @property
    def patients(self) -> int:
        """Number of patients with a live detector."""
        return len(self._detectors)


@lru_cache(maxsize=1)
def get_registry() -> DetectorRegistry:
    """Return the process-wide registry, configured from ``DETECTOR_*`` variables."""
    return DetectorRegistry(load_config())
