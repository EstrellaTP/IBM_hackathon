"""Domain logic of the suspicion-module service, free of web-framework imports.

Suspicion module: when the clinician selects a suspicion (depression), computes
the features of the recording, runs the calibrated classifier and SHAP, and returns
a ModuleResult.
"""

from __future__ import annotations
