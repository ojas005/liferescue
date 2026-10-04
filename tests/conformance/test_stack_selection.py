"""The stack under test is chosen by env LR_STACK=fake|real (default fake)."""

import pytest

from lr_support.stack import REAL_SKIP_REASON, STACK_KINDS, FakeStack, make_stack_factory, selected_kind


def test_default_is_fake(monkeypatch):
    monkeypatch.delenv("LR_STACK", raising=False)
    assert selected_kind() == "fake"


@pytest.mark.parametrize("raw,kind", [("fake", "fake"), ("FAKE", "fake"), (" real ", "real"), ("", "fake")])
def test_env_values(monkeypatch, raw, kind):
    monkeypatch.setenv("LR_STACK", raw)
    assert selected_kind() == kind


def test_unknown_value_is_a_usage_error(monkeypatch):
    monkeypatch.setenv("LR_STACK", "mock")
    with pytest.raises(pytest.UsageError):
        selected_kind()


def test_fake_factory_builds_the_contract_fake_stack():
    assert make_stack_factory("fake") is FakeStack


def test_real_stack_is_skipped_with_a_reason_until_wired():
    with pytest.raises(pytest.skip.Exception) as ei:
        make_stack_factory("real")()
    assert "not wired" in str(ei.value) and REAL_SKIP_REASON in str(ei.value)


def test_kinds():
    assert STACK_KINDS == ("fake", "real")


def test_fake_stack_uses_the_mock_model_only_in_tests(stack):
    """The fake stack is the only place MockModel is wired; production config must never select it (CONTRACT-README s4 item 4)."""
    assert stack.model.adapter_kind == "mock"
