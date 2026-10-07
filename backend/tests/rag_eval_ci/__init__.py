"""Record/replay support for the no-cloud RAG evaluation CI (RFC v3 §8.2).

Modules:
- ``replay`` — key derivation, recording IO, material fingerprint (shared by
  the recorder and the replay service so they agree by construction);
- ``capture`` — the in-process capture wrapper used by the recording pass.
"""
