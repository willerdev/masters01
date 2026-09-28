"""Bot token used to contact an account and close AI trading."""

from alembic import op

revision = "0008_bot_token"
down_revision = "0007_risk_pause"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS bot_token_hash VARCHAR(64) NOT NULL DEFAULT ''")
    op.execute("CREATE INDEX IF NOT EXISTS ix_accounts_bot_token_hash ON accounts (bot_token_hash)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_accounts_bot_token_hash")
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS bot_token_hash")
