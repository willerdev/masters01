"""Temporary pause for risk blocks on an account."""

from alembic import op

revision = "0007_risk_pause"
down_revision = "0006_ai_trading"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS risk_blocks_paused BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS risk_blocks_paused")
