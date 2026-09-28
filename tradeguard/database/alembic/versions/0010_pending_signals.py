"""Pending Telegram signals that expire after 10 minutes."""

from alembic import op

revision = "0010_pending_signals"
down_revision = "0009_telegram_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_signals (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            chat_id VARCHAR(32) NOT NULL,
            chat_title VARCHAR(120) NOT NULL DEFAULT '',
            message_id BIGINT NOT NULL,
            symbol VARCHAR(64) NOT NULL,
            side VARCHAR(8) NOT NULL,
            entry NUMERIC(20, 10) NOT NULL,
            stop_loss NUMERIC(20, 10),
            take_profit NUMERIC(20, 10),
            volume NUMERIC(18, 8) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, chat_id, message_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_pending_signals_org_time ON pending_signals (organization_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pending_signals")
