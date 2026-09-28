"""Allow DeepSeek to trade a connected account."""

from alembic import op

revision = "0006_ai_trading"
down_revision = "0005_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS ai_trading_enabled BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS ai_trading_enabled")
