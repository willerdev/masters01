"""Watched Telegram setups that become limit orders only after entry, stop, and target are read."""

from alembic import op

revision = "0016_setup_watches"
down_revision = "0015_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS setup_watches (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            account_id UUID REFERENCES accounts(id),
            chat_id VARCHAR(32) NOT NULL DEFAULT '',
            symbol VARCHAR(64) NOT NULL,
            side VARCHAR(8) NOT NULL,
            entry NUMERIC(20, 10) NOT NULL,
            stop_loss NUMERIC(20, 10) NOT NULL,
            take_profit NUMERIC(20, 10) NOT NULL,
            volume NUMERIC(18, 8) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'watching',
            order_sent BOOLEAN NOT NULL DEFAULT FALSE,
            notified BOOLEAN NOT NULL DEFAULT FALSE,
            note VARCHAR(300) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_setup_watches_organization_id ON setup_watches (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_setup_watches_status ON setup_watches (status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS setup_watches")
