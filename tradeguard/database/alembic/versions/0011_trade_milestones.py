"""Milestones already announced for an open trade."""

from alembic import op

revision = "0011_trade_milestones"
down_revision = "0010_pending_signals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_milestones (
            id UUID PRIMARY KEY,
            account_id UUID NOT NULL REFERENCES accounts(id),
            ticket VARCHAR(64) NOT NULL,
            code VARCHAR(32) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (account_id, ticket, code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_trade_milestones_account ON trade_milestones (account_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trade_milestones")
