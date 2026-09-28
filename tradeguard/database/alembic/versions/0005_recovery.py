"""Account recovery record for the second next of kin."""

from alembic import op

revision = "0005_recovery"
down_revision = "0004_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS account_recoveries (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL UNIQUE REFERENCES organizations(id),
            user_id UUID NOT NULL REFERENCES users(id),
            email VARCHAR(320) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            trc20_wallet VARCHAR(64) NOT NULL,
            next_of_kin_name VARCHAR(200) NOT NULL,
            second_next_of_kin_name VARCHAR(200) NOT NULL,
            claim_token_hash VARCHAR(64) UNIQUE,
            claim_token_expires_at TIMESTAMPTZ,
            restored_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_account_recoveries_user_id ON account_recoveries (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_recoveries")
