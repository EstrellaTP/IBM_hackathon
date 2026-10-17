# GigaFly_IBM Z Datathon 2026 Project

## A Holter for Mental Health

Real-time anomaly detection on a wearable, momentary questions to the patient, and objective evidence for the clinician, running on **IBM LinuxONE**.

> Work in progress during the IBM Z Datathon 2026 (Theme 1: *Real-Time AI for Critical Decisions*). Team **GigaFly**, Universidad Carlos III de Madrid.

### The problem
One in seven people worldwide lives with a mental disorder, yet psychiatric diagnosis still relies almost entirely on clinical interviews and subjective scales. In bipolar disorder, 5 to 8 years pass on average before adequate treatment; a Madrid cohort reports 9.3 years.

### What it does
1. The patient wears an activity and heart-rate band.
2. A model compares the live signal with the patient's own baseline. When it detects an anomaly that movement does not explain, it immediately asks the patient a short question on their phone: *what were you doing, and how do you feel?*
3. The clinician selects the suspicion to test (e.g. depression). Only that module runs and returns an **evidence dashboard**: one chart per metric against age- and sex-specific reference ranges, with the metrics that drove the result highlighted.
4. During therapy, a **before-and-now** view tracks how the metrics evolve.

The system does not diagnose or prescribe, generates no narrative about the patient and never calls emergency services on its own. The professional always decides.

### Architecture (planned)
Five services in Docker on LinuxONE: encrypted ingestion API, real-time episode detector, encrypted pseudonymised store, suspicion module (calibrated classifier + SHAP) and evidence API with the clinician dashboard. See `docs/architecture.md` (coming soon).

### Data
NHANES (CDC), DEPRESJON (Simula), a hospital nurse stress dataset (Scientific Data, 2022) and WESAD (University of Siegen). Datasets are **not** redistributed in this repository; see `ml/data/` for download scripts and `ATTRIBUTIONS.md` for citations.

### Status
Under active development. Setup, metrics, screenshots and the demo video will be added here.
