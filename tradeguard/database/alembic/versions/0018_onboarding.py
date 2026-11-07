"""User onboarding profiles — personal info, wallet, and activity selections."""

from alembic import op

revision = "0018_onboarding"
down_revision = "0017_naked_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS onboarding_profiles (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id),
            email VARCHAR(320) NOT NULL DEFAULT '',
            age INTEGER NOT NULL,
            country VARCHAR(120) NOT NULL,
            wallet_network VARCHAR(40) NOT NULL,
            wallet_address VARCHAR(200) NOT NULL,
            activities JSONB NOT NULL DEFAULT '[]',
            indices_broker VARCHAR(60) NOT NULL DEFAULT '',
            completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_onboarding_profiles_user_id UNIQUE (user_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_onboarding_profiles_user_id ON onboarding_profiles (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS onboarding_profiles")
