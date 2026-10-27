"""Shared test fixture for broker tests (not a test module: no ``test_`` prefix).

Builds a broker over the in-memory mock backend with a fake clock. All secret values are
random canaries generated at runtime.
"""

from datetime import timedelta

from packages.secrets.audit import InMemoryAuditSink
from packages.secrets.broker import CredentialBroker
from packages.secrets.codes import RequestReason
from packages.secrets.config import BrokerConfig
from packages.secrets.memory_backend import InMemoryBackend
from packages.secrets.policy import policy_from_mapping
from packages.secrets.secret_types import (
    CallContext,
    CredentialRequest,
    Environment,
    Purpose,
    SecretRef,
)
from packages.secrets.tasks import InMemoryTaskRegistry
from packages.secrets.testing import FakeClock, make_canary

MODEL_REF = SecretRef(Environment.MOCK, Purpose.MODEL_INFERENCE, "mock-model-key")
SEARCH_REF = SecretRef(Environment.MOCK, Purpose.WEB_SEARCH, "mock-search-key")
DB_REF = SecretRef(Environment.MOCK, Purpose.DB_APP, "mock-db-app-key")

DEFAULT_POLICY = {
    "version": 1,
    "grants": [
        {
            "agent_id": "LR-06",
            "purpose": "model_inference",
            "names": ["mock-model-key", "mock-model-key-b", "mock-model-key-c"],
            "environments": ["mock"],
            "max_ttl_seconds": 900,
        },
        {
            "agent_id": "LR-06",
            "purpose": "web_search",
            "names": ["mock-search-key"],
            "environments": ["mock"],
        },
        {
            "agent_id": "LR-04",
            "purpose": "db_app",
            "names": ["mock-db-app-key"],
            "environments": ["mock"],
            "max_ttl_seconds": 600,
        },
    ],
}

PURPOSE_REASON = {
    Purpose.MODEL_INFERENCE: RequestReason.MODEL_CALL,
    Purpose.WEB_SEARCH: RequestReason.WEB_SEARCH_CALL,
    Purpose.DB_APP: RequestReason.DB_ACCESS,
}


class Rig:
    """broker + mock backend + fake clock + audit sink + task registry, with canaries seeded."""

    def __init__(
        self,
        config=None,
        policy_doc=None,
        gateways=("model-gateway", "tool-gateway"),
        tasks=(("T-1", "R-1", "LR-06"),),
    ):
        self.clock = FakeClock()
        self.backend = InMemoryBackend()
        self.registry = InMemoryTaskRegistry()
        self.sink = InMemoryAuditSink()
        self.alerts = []
        self.canaries = {}
        for ref in (MODEL_REF, SEARCH_REF, DB_REF):
            self.seed(ref)
        for name in ("mock-model-key-b", "mock-model-key-c"):
            self.seed(SecretRef(Environment.MOCK, Purpose.MODEL_INFERENCE, name))
        for task_id, run_id, agent_id in tasks:
            self.registry.register(task_id, run_id, agent_id)
        self.broker = CredentialBroker(
            backend=self.backend,
            policy=policy_from_mapping(policy_doc or DEFAULT_POLICY),
            task_registry=self.registry,
            config=config or BrokerConfig(),
            clock=self.clock,
            audit_sink=self.sink,
            alert_handler=self.alerts.append,
            gateway_ids=gateways,
        )
        self.gateways = self.broker.issue_gateway_identities()

    def seed(self, ref):
        value = make_canary()
        self.backend.provision(ref, value)
        self.canaries[ref] = value
        return value

    def request(
        self, ref=MODEL_REF, *, task="T-1", run="R-1", agent="LR-06", ttl=None, **kw
    ):
        req = CredentialRequest(
            task_id=task,
            run_id=run,
            agent_id=agent,
            ref=ref,
            reason_code=PURPOSE_REASON[ref.purpose],
            requested_ttl=ttl,
            **kw,
        )
        return self.broker.request(req)

    def ctx(self, handle, **over):
        base = dict(
            task_id=handle.task_id, run_id=handle.run_id, agent_id=handle.agent_id
        )
        base.update(over)
        return CallContext(**base)

    def use(self, handle, gateway="model-gateway", **over):
        return self.broker.use(
            handle, caller=self.gateways[gateway], context=self.ctx(handle, **over)
        )

    def events(self, *types):
        evs = self.sink.events
        return [e for e in evs if not types or e.event_type in {t.value for t in types}]

    def all_audit_text(self):
        return repr([e.to_dict() for e in self.sink.events])

    def minutes(self, n):
        self.clock.advance(timedelta(minutes=n).total_seconds())
