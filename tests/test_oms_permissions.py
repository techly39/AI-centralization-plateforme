"""The OMS and the API must never disagree about who may trade.

Both layers check whether an order is allowed: the API through
``Depends(require(Action.PLACE_ORDER))``, the OMS through
``_validate_request``. That is intentional defence in depth — ``place_order``
is safe to call from a script or a Phase 3 backtest driver, not only from a
route.

The danger of a duplicated check is that the copies drift. These tests exist to
make drift impossible: they assert that the OMS's answer is *derived from* the
same permission matrix the API uses, rather than being a second opinion about
roles. If someone reintroduces a hardcoded role list in the OMS,
``test_the_oms_follows_the_matrix_it_does_not_hardcode_roles`` fails.
"""

from __future__ import annotations

import pytest

from app.db.models import AgentRole
from app.oms import RoleNotPermittedError, place_order
from app.registry.permissions import Action, has_permission
from app.registry.service import register_agent

ALL_ROLES = [AgentRole.analyst, AgentRole.pm, AgentRole.management, AgentRole.system]


def _agent(SessionFactory, name: str, role: AgentRole, pod_id: int | None):
    session = SessionFactory()
    try:
        agent, _ = register_agent(session, name=name, role=role, pod_id=pod_id)
        session.commit()
        return agent
    finally:
        session.close()


@pytest.mark.parametrize("role", ALL_ROLES)
def test_the_oms_agrees_with_the_matrix_for_every_role(
    role, SessionFactory, make_pod, fund_pod_cash, prices, db
):
    """For each role, the OMS raises exactly when the matrix says no."""
    make_pod(1)
    fund_pod_cash(1, 100_000.0)
    actor = _agent(SessionFactory, f"{role.value}-1", role, pod_id=1)
    allowed = has_permission(role, Action.PLACE_ORDER)

    session = SessionFactory()
    try:
        actor = session.get(type(actor), actor.id)
        if allowed:
            order = place_order(
                session, actor=actor, ticker="AAPL", side="buy", qty=1,
                price_type="market", justification="matrix check", provider=prices,
            )
            assert order.status.value == "filled"
        else:
            with pytest.raises(RoleNotPermittedError):
                place_order(
                    session, actor=actor, ticker="AAPL", side="buy", qty=1,
                    price_type="market", justification="matrix check",
                    provider=prices,
                )
    finally:
        session.close()


def test_the_oms_follows_the_matrix_it_does_not_hardcode_roles(
    SessionFactory, make_pod, fund_pod_cash, prices, monkeypatch
):
    """Grant an analyst the right to trade and the OMS must obey.

    The point is not that analysts should trade — they should not. The point is
    that the OMS has no private opinion about roles: change the one matrix in
    ``app/registry/permissions.py`` and every layer follows.
    """
    from app.registry import permissions

    make_pod(1)
    fund_pod_cash(1, 100_000.0)
    analyst = _agent(SessionFactory, "analyst-1", AgentRole.analyst, pod_id=1)

    session = SessionFactory()
    try:
        actor = session.get(type(analyst), analyst.id)

        # Before: the matrix says no, so the OMS says no.
        with pytest.raises(RoleNotPermittedError):
            place_order(
                session, actor=actor, ticker="AAPL", side="buy", qty=1,
                price_type="market", justification="before", provider=prices,
            )

        # Widen the matrix — and only the matrix.
        widened = dict(permissions._MATRIX)
        widened[AgentRole.analyst] = widened[AgentRole.analyst] | {Action.PLACE_ORDER}
        monkeypatch.setattr(permissions, "_MATRIX", widened)

        order = place_order(
            session, actor=actor, ticker="AAPL", side="buy", qty=1,
            price_type="market", justification="after", provider=prices,
        )
        assert order.status.value == "filled"
    finally:
        session.close()


def test_the_pod_scope_check_is_the_oms_s_own_job(
    SessionFactory, make_pod, fund_pod_cash, prices
):
    """A PM with the right role but no pod still cannot trade.

    This is the "(own pod)" qualifier from the TRD §6 table — a role → action
    matrix cannot express it, which is why the OMS keeps a check of its own.
    """
    from app.oms import PodScopeError

    make_pod(1)
    fund_pod_cash(1, 100_000.0)
    homeless = _agent(SessionFactory, "pm-nopod", AgentRole.pm, pod_id=None)
    assert has_permission(AgentRole.pm, Action.PLACE_ORDER) is True

    session = SessionFactory()
    try:
        actor = session.get(type(homeless), homeless.id)
        with pytest.raises(PodScopeError):
            place_order(
                session, actor=actor, ticker="AAPL", side="buy", qty=1,
                price_type="market", justification="no pod", provider=prices,
            )
    finally:
        session.close()


def test_cancelling_is_gated_by_the_same_matrix_entry(
    client, desk, admin_key, SessionFactory, prices
):
    """Management may not cancel a PM's order — TRD §6 gives it no place_order.

    Checked through the API and again directly against the service, so the
    guarantee does not depend on going through a route.
    """
    from app.oms import cancel_order

    _, _, pm_key = desk
    order_id = client.post(
        "/orders", headers={"X-API-Key": pm_key},
        json={"ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "limit",
              "limit_price": 150.0, "justification": "queued"},
    ).json()["id"]

    assert client.delete(
        f"/orders/{order_id}", headers={"X-API-Key": admin_key}
    ).status_code == 403

    session = SessionFactory()
    try:
        from app.db.models import Agent
        from sqlalchemy import select

        manager = session.scalar(select(Agent).where(Agent.role == AgentRole.management))
        with pytest.raises(RoleNotPermittedError):
            cancel_order(session, actor=manager, order_id=order_id)
    finally:
        session.close()
