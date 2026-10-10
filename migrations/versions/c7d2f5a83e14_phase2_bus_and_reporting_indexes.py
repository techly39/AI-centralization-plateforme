"""phase 2: indexes for the bus, cost reports, and work logs

No new columns — Phase 0 declared the whole schema. What changes is that these
tables are now *read* on every polling loop and every metrics call, so the
columns those queries filter on get indexes:

  messages.to_ref     the visibility filter behind GET /messages runs on it for
                      every poll every agent makes
  messages.from_agent "messages sent by this pod" joins through it
  costs.pod_id        cost totals per pod
  costs.agent_id      cost attributed to one agent
  tasks.pod_id        task counts and time-per-subject per pod
  tasks.agent_id      an agent's own work log

Without them SQLite table-scans, which is invisible at ten rows and painful at a
million — and a message table grows every time any agent says anything.

Revision ID: c7d2f5a83e14
Revises: b1c4d7f90a21
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d2f5a83e14"
down_revision: Union[str, None] = "b1c4d7f90a21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (table, column) pairs, indexed as ``ix_<table>_<column>`` to match Phase 1.
_INDEXES: tuple[tuple[str, str], ...] = (
    ("messages", "to_ref"),
    ("messages", "from_agent"),
    ("costs", "pod_id"),
    ("costs", "agent_id"),
    ("tasks", "pod_id"),
    ("tasks", "agent_id"),
)


def upgrade() -> None:
    for table, column in _INDEXES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_index(batch_op.f(f"ix_{table}_{column}"), [column], unique=False)


def downgrade() -> None:
    for table, column in reversed(_INDEXES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(batch_op.f(f"ix_{table}_{column}"))
