"""Organization Telegram app id, API hash, and bot token."""

from alembic import op

revision = "0009_telegram_config"
down_revision = "0008_bot_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_configs (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL UNIQUE REFERENCES organizations(id),
            secret_nonce BYTEA,
            secret_ciphertext BYTEA,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS telegram_configs")
