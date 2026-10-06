"""Video ingestion subsystem (spec 2026-09-08).

Shot-card pipeline: probe → ASR → scene segmentation → keyframe+OCR → VLM
caption → materialize (``video_shots`` rows + shot-card ``chunks``). Text is
the primary index: the assembled card body rides the existing vector / graph
/ wiki legs untouched — this package owns the media-side extraction only.
"""
