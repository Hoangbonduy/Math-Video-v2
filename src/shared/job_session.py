"""Durable model calls, accounting and project generation locks."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import json
import uuid
from src.shared import _workflow_store as store
from src.shared._workflow_store import WorkflowError
from src.shared.ai_client import SUBSCRIPTION_SOURCES
from src.shared.ai_config import BUDGET_USD, MAX_REQUESTS
from src.shared.ai_utils import redact


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def _used(job):
    return float(sum((Decimal(str(c["actual_cost_usd"])) if c.get("actual_cost_usd") is not None and not c.get("usage_incomplete")
                      else Decimal(str(c["reserved_cost_usd"])) if c["status"] != "rejected" else Decimal(0))
                     for c in job["calls"] if c.get("billing_source") not in SUBSCRIPTION_SOURCES))


class Session:
    def __init__(self, directory, job, client, retry_uncertain=None, *, budget_usd=BUDGET_USD, other_used=0, max_requests=MAX_REQUESTS):
        self.directory, self.job, self.client = directory, job, client
        self.budget_usd, self.other_used = budget_usd, other_used
        self.max_requests = max_requests
        self.retry_uncertain = retry_uncertain
        if retry_uncertain is not None and not any(c["call_id"] == retry_uncertain and c["status"] in ("in_flight", "uncertain") for c in job["calls"]):
            raise WorkflowError("UNKNOWN_REQUEST", "Select an uncertain call_id from status for this job")

    def save(self):
        self.job["updated_at"] = _now()
        store.atomic_write(self.directory / "job.json", redact(self.job))

    def settle(self, entry, response):
        usage=response.get('usage',{})
        if (entry.get('billing_source') not in SUBSCRIPTION_SOURCES
                or usage.get('billing_source')!=entry.get('billing_source')):
            raise WorkflowError('AI_CONFIG','Saved response is not a Codex subscription result; start a fresh job')
        entry.update(status='complete',request_id=response.get('id'),model=response.get('model'),
            usage=usage,actual_cost_usd=None,billing_source=entry['billing_source'],
            finished_at=entry.get('finished_at') or _now())
        entry.pop('usage_incomplete',None)
        self.save()
        return response

    def call(self, phase, messages, *, schema=None, search=False, client=None, pricing=None):
        from src.shared.task_control import checkpoint
        checkpoint()
        call_client = client or self.client
        call_pricing = pricing or self.job.get("pricing")
        subscription = getattr(call_client,"billing_source",None) in SUBSCRIPTION_SOURCES
        if not subscription:
            raise WorkflowError('AI_CONFIG','Only a Codex subscription client can create model calls')
        previous = [c for c in self.job["calls"] if c["phase"] == phase]
        if any(c.get('billing_source') not in SUBSCRIPTION_SOURCES for c in previous):
            raise WorkflowError('AI_CONFIG','Historical non-Codex calls are read-only; start a fresh job')

        for entry in reversed(previous):
            path = self.directory / "calls" / (entry["call_id"] + ".json")
            if path.exists():
                if entry.get("response_sha256") and store.digest(path) != entry["response_sha256"]:
                    raise WorkflowError("CACHE_CORRUPT", "Saved Codex response checksum changed")
                response = store.read_json(path)
                entry["response_sha256"] = store.digest(path)
                return self.settle(entry, response)
            if entry["status"] == "complete":
                raise WorkflowError("CACHE_CORRUPT", "Completed Codex response is missing; not rerunning")
        for entry in previous:
            if entry["status"] in ("in_flight", "uncertain"):
                entry["status"] = "uncertain"
                self.save()
                if entry.get("retry_authorized"):
                    continue
                if self.retry_uncertain != entry["call_id"]:
                    raise WorkflowError('CODEX_RESULT_UNKNOWN',
                        f"Codex call {entry['call_id']} is incomplete; select --retry-uncertain explicitly")
                self.retry_uncertain = None
                entry["retry_authorized"] = True
                self.save()
        if len(self.job["calls"]) >= self.max_requests:
            raise WorkflowError("REQUEST_LIMIT", "Request/retry limit reached")
        if search and any(c.get("search") and c["status"] != "rejected" and not c.get("retry_authorized") for c in self.job["calls"]):
            raise WorkflowError("SEARCH_LIMIT", "Two search uses were already reserved; no more search requests")
        if search:
            self.job["pricing"].update(self.client.search_pricing())
            self.save()
        payload = call_client.payload(messages, call_pricing or self.job["pricing"], schema=schema, search=search)
        entry = dict(call_id=uuid.uuid4().hex,phase=phase,status='in_flight',search=search,
                     started_at=_now(),reserved_cost_usd=0,actual_cost_usd=None,
                     billing_source=call_client.billing_source)
        payload['_execution']=dict(directory=str(self.directory),call_id=entry['call_id'],phase=phase)
        self.job["calls"].append(entry)
        previous.append(entry)
        self.save()  # Persist the call identity BEFORE launching Codex.
        try:
            response = call_client.complete(payload)
        except Exception as exc:
            if isinstance(exc,WorkflowError) and exc.code=='TASK_PAUSED':
                entry.update(status='interrupted',error_code=exc.code,error=exc.message,finished_at=_now())
                self.save()
                raise
            if isinstance(exc, WorkflowError) and exc.code in ('CODEX_LOGIN_REQUIRED','CODEX_NOT_FOUND','CODEX_CONFIG','CODEX_USAGE_LIMIT'):
                entry.update(status="rejected", error_code=exc.code, error=exc.message)
                self.save()
                raise
            entry.update(status="uncertain", error=redact(str(exc)))
            self.save()
            code=exc.code if isinstance(exc,WorkflowError) else 'CODEX_RESULT_UNKNOWN'
            raise WorkflowError(code,redact(str(exc))+'; logs saved, no automatic retry') from None
        path = self.directory / "calls" / (entry["call_id"] + ".json")
        path.parent.mkdir(exist_ok=True)
        # A kill between this durable write and ledger update is recoverable.
        store.atomic_write(path, redact(response))
        entry["response_sha256"] = store.digest(path)
        return self.settle(entry, response)

@contextmanager
def _job_lock(root):
    try:
        with (root / ".ai-generation.lock").open("a+b") as file:
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkflowError("GENERATION_BUSY", "Another generation is running for this project") from None
            try:
                yield
            finally:
                fcntl.flock(file, fcntl.LOCK_UN)
    except OSError as exc:
        raise WorkflowError("IO_ERROR", redact(str(exc))) from None

