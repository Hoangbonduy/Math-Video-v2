"""Provider-neutral sanitization, response validation and HTTP redirect policy."""
import os
import re
import urllib.request
from src.shared.ai_config import get_model
from src.shared._workflow_store import WorkflowError

def redact(value):
    """Sanitize strings recursively before persistence or user-facing errors."""
    if isinstance(value, str):
        for name in os.environ:
            if not (name.endswith('API_KEY') or name.endswith('ACCESS_TOKEN')):
                continue
            key = os.environ.get(name, "")
            if key:
                value = value.replace(key, "[REDACTED]")
        return re.sub(r"sk-[A-Za-z0-9_-]+|Bearer\s+[^\s\"']+", "[REDACTED]", value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if k.lower() not in ("authorization", "api_key", "api-key", "fpt_api_key")}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def response_text(response):
    if response.get("model") != get_model():
        raise WorkflowError("MODEL_MISMATCH", "Response did not come from the configured model")
    try:
        choice = response["choices"][0]
        if choice.get("finish_reason") not in ("stop", None):
            raise ValueError("Truncated or unfinished response")
        value = choice["message"]["content"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Empty response text")
        return value
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WorkflowError("INVALID_MODEL_OUTPUT", str(exc)) from None
