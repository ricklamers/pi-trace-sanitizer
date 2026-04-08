"""Configuration constants for the trace sanitizer."""

from pathlib import Path

DEFAULT_MODEL_PATH = "mlx-community/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4"

ENTITY_TYPES = [
    "PERSON",
    "EMAIL",
    "API_KEY",
    "INTERNAL_URL",
    "IP_ADDR",
    "USER_PATH",
    "CREDENTIAL",
    "ORG_NAME",
    "EMPLOYEE_ID",
    "PHONE",
    "SENSITIVE_DATA",
]

SYSTEM_PROMPT = """\
You are a PII and sensitive data detector for software development traces.
Given text from a coding agent session, list ALL sensitive items you find.
Output one item per line in the format: TYPE: exact text
Types: PERSON, EMAIL, API_KEY, INTERNAL_URL, IP_ADDR, USER_PATH, CREDENTIAL, ORG_NAME, EMPLOYEE_ID, PHONE, SENSITIVE_DATA
Only list items that appear verbatim in the input. Do not explain.
If no sensitive data is found, output: NONE"""

USER_PROMPT_TEMPLATE = """\
Analyze the following text from a coding agent trace and list all PII or sensitive data found:

---
{text}
---"""

DEFAULT_SERVER_PORT = 8080
DEFAULT_SERVER_URL = f"http://localhost:{DEFAULT_SERVER_PORT}"

IMAGE_DATA_MIN_LENGTH = 256
MAX_TOKENS_PER_GENERATION = 32768
MIN_ENTITY_TEXT_LENGTH = 4

ALLOWLISTED_TERMS = frozenset({
    "email", "credentials", "password", "secret", "token",
    "nvidia.com", "github.com", "npmjs.com", "pypi.org",
    "localhost", "example.com", "example.org",
})
