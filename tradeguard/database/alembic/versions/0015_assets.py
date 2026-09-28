"""Crypto asset deposits and withdrawals recorded from NOWPayments."""

from alembic import op

revision = "0015_assets"
down_revision = "0014_wallets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_transfers (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            user_id UUID NOT NULL REFERENCES users(id),
            currency VARCHAR(20) NOT NULL,
            direction VARCHAR(16) NOT NULL,
            amount NUMERIC(28, 8) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            address VARCHAR(180) NOT NULL DEFAULT '',
            provider_id VARCHAR(80) NOT NULL DEFAULT '',
            order_id VARCHAR(80) NOT NULL DEFAULT '',
            invoice_url VARCHAR(500) NOT NULL DEFAULT '',
            note VARCHAR(240) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_asset_transfers_organization_id ON asset_transfers (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_asset_transfers_user_id ON asset_transfers (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_asset_transfers_provider_id ON asset_transfers (provider_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_asset_transfers_order_id ON asset_transfers (order_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS asset_transfers")
