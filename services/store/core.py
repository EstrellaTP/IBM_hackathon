"""Domain logic of the store service, free of web-framework imports.

Encrypted, pseudonymised storage: signal batches, episodes, answers and the
append-only audit log. Sensitive fields are encrypted at rest with Fernet.
"""

from __future__ import annotations
