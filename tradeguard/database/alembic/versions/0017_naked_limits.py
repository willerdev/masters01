"""Reminders for limits that were sent after the broker rejected the stop."""

from alembic import op

revision = "0017_naked_limits"
down_revision = "0016_setup_watches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS naked_limits (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            account_id UUID NOT NULL REFERENCES accounts(id),
            ticket VARCHAR(64) NOT NULL DEFAULT '',
            symbol VARCHAR(64) NOT NULL,
            side VARCHAR(8) NOT NULL,
            entry NUMERIC(20, 10) NOT NULL,
            volume NUMERIC(18, 8) NOT NULL,
            ignored_stop NUMERIC(20, 10),
            last_reminded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_naked_limits_organization_id ON naked_limits (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_naked_limits_account_id ON naked_limits (account_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS naked_limits")
