# pi-trace-sanitizer

Local PII and sensitive data sanitizer for [pi](https://pi.dev) coding agent session traces. Uses a local [Nemotron 3 Nano 30B](https://huggingface.co/mlx-community/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4) model via [mlx-lm](https://github.com/ml-explore/mlx-examples/tree/main/llms) to detect and mask personal information before sharing traces publicly.

## What it does

Given a pi session JSONL file, the sanitizer:

1. Walks every text field in every event
2. Sends each field to a local LLM with a PII detection prompt
3. Replaces detected entities with consistent placeholders (`[PERSON_1]`, `[EMAIL_1]`, etc.)
4. Normalizes user paths (`/Users/rlamers/` → `/Users/user/`)
5. Writes sanitized output

Detected entity types: `PERSON`, `EMAIL`, `API_KEY`, `INTERNAL_URL`, `IP_ADDR`, `USER_PATH`, `CREDENTIAL`, `ORG_NAME`, `EMPLOYEE_ID`, `PHONE`, `SENSITIVE_DATA`

## Install

Requires Python 3.12+ and an Apple Silicon Mac (for MLX).

```bash
uv sync
```

## Usage

Two-step workflow: start the model server once, then sanitize sessions.

### Start the server

```bash
# Uses the default HF model (downloads ~19 GB on first run)
uv run pi-trace-sanitizer server

# Or use a local model checkout
uv run pi-trace-sanitizer server --model models/NVFP4
```

### Sanitize sessions

```bash
# Sanitize all .jsonl files in a directory
uv run pi-trace-sanitizer /path/to/sessions/

# Sanitize a single file
uv run pi-trace-sanitizer session.jsonl

# Custom output directory + persistent entity map
uv run pi-trace-sanitizer /path/to/sessions/ \
  -o ./sanitized \
  --entity-map ./entity_map.json

# Dry-run (report detections without writing output)
uv run pi-trace-sanitizer --dry-run session.jsonl

# Quiet mode (just detections, no TUI)
uv run pi-trace-sanitizer -q session.jsonl
```

### Use with pi-share-hf

Slot it in between `collect` (secret redaction + TruffleHog) and `review` (cloud LLM shareability check):

```bash
# 1. Keep server running
uv run pi-trace-sanitizer server

# 2. Collect and redact exact secrets
pi-share-hf collect --secret secrets.txt --deny deny.txt ...

# 3. Sanitize PII in the redacted output
uv run pi-trace-sanitizer .pi/hf-sessions/redacted/ \
  -o .pi/hf-sessions/redacted/ \
  --entity-map .pi/hf-sessions/entity_map.json

# 4. Review and upload
pi-share-hf review README.md
pi-share-hf upload
```

## Model

Default: [`mlx-community/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4`](https://huggingface.co/mlx-community/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4)

- NVIDIA's QAT-calibrated FP4 checkpoint converted to MLX format (~19 GB)
- Thinking mode enabled by default (higher PII detection accuracy)
- Recommended sampling: `temperature=1.0`, `top_p=1.0`

Use `--no-thinking` for faster but lower quality detection.

## Tests

```bash
uv run pytest tests/ -v
```

All tests run without the model (mock detector).

## License

Apache 2.0
