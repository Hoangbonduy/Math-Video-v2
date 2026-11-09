"""Select an explicit AI backend; never fall back to a paid API."""
from src.shared.ai_config import get_backend


def create_text_client():
    from src.shared.codex_client import CodexClient
    get_backend()  # Reject obsolete/unsupported settings rather than falling back.
    return CodexClient()


SUBSCRIPTION_SOURCES = ('codex_subscription',)


def subscription_billing(backend=None):
    return {'codex':'codex_subscription'}.get(backend or get_backend())


def subscription_summary(calls, billing_source=None):
    billing_source = billing_source or subscription_billing() or 'codex_subscription'
    selected = [c for c in calls if c.get('billing_source') == billing_source]
    def total(key):
        values = [c.get('usage', {}).get(key) for c in selected if c['status'] == 'complete']
        return sum(values) if values and all(type(v) is int for v in values) else None
    return dict(billing_source=billing_source, budget_usd=None, budget_used_usd=None,
                request_count=len(selected), input_tokens=total('prompt_tokens'), output_tokens=total('completion_tokens'),
                quota_remaining=None, usage_label='Hạn mức Codex · tài khoản ChatGPT')
