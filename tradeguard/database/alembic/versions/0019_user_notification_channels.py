"""Per-user notification channels (e.g. personal Telegram chat)."""

from alembic import op

revision = "0019_user_notification_channels"
down_revision = "0018_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_notification_channels (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id),
            channel VARCHAR(32) NOT NULL,
            destination VARCHAR(200) NOT NULL,
            verified BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_notification_channels_user_channel UNIQUE (user_id, channel)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_notification_channels_user_id ON user_notification_channels (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_notification_channels")
