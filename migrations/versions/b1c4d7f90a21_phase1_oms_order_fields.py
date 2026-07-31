"""phase 1: order economics fields + OMS query indexes

Adds to ``orders``:
  fee            — simulated commission actually charged on the fill
  realized_pnl   — booked P&L on a sell, net of that sell's fee
  status_reason  — why an order was rejected or cancelled, in plain words

All three duplicate what the ``order_filled`` / ``order_rejected`` events
already record. That is deliberate: ``GET /orders`` must be able to answer
"what did this cost me" without replaying the ledger. The events stay the
source of truth.

Also indexes the columns the pending-order monitor filters on, so its sweep
stays O(pending) rather than O(all orders ever).

Revision ID: b1c4d7f90a21
Revises: e2eaf48452c2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c4d7f90a21"
down_revision: Union[str, None] = "e2eaf48452c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fee", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("realized_pnl", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("status_reason", sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f("ix_orders_pod_id"), ["pod_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_orders_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_orders_ticker"), ["ticker"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_orders_ticker"))
        batch_op.drop_index(batch_op.f("ix_orders_status"))
        batch_op.drop_index(batch_op.f("ix_orders_pod_id"))
        batch_op.drop_column("status_reason")
        batch_op.drop_column("realized_pnl")
        batch_op.drop_column("fee")
