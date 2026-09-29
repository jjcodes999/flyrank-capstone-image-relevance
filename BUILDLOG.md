# BUILDLOG

How I used AI on this project, phase by phase. I built it with Claude Code (an AI coding
agent) doing most of the typing; I set the requirements, stack and constraints, and I
review and own every line. Entries are short and honest, including the AI's mistakes.

## Phase 1 - Design and dataset

- **AI generated:** the first draft of `docs/design.md`, the image picks in
  `data/manifest.csv` (it browsed Pexels search pages and read photo IDs, descriptions
  and photographer names from the page data), and `scripts/download_images.py`.
- **Where it was wrong:**
  - The download script reported "48 downloaded, 1 failed" for 48 images. The "failure"
    was a `print()` crashing on the photographer name "Vaičiulėnas" (Windows console is
    cp1252) *after* the file had been saved. Fixed by switching stdout to UTF-8; a rerun
    now reports `1 downloaded, 47 already present, 0 failed`.
  - The model download command ended with `echo exit=$?`, which reported success even
    though `ollama pull qwen3-vl:4b` had failed with a TLS timeout. It was caught by
    `ollama list`, and the pull was retried in a loop.
- **What I checked / decided:**
  - Stack and constraints are mine: Python/FastAPI, Postgres + pgvector, local Ollama
    (`qwen3-vl:4b` for vision, `all-minilm` for embeddings), $0, no paid APIs.
  - Before designing matching, the AI measured `all-minilm` directly: "Vulpes vulpes"
    vs "red fox" = 0.26, vs "gray wolf" = 0.26, vs "coyote" = 0.34. So plain embeddings
    **cannot** do the scientific-name match. The decision: add a post-analysis step
    that turns each post into a common-name subject before embedding.
  - Corpus checked on a contact sheet: 48 images, and all the ambiguous ones really
    are ambiguous (bokeh, blurred fox, dark motion-blurred dog).
  - Filenames like `fox_01.jpg` are only for humans. The pipeline sends pixels only,
    never the filename, so the model can't cheat.
