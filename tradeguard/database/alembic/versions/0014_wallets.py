"""Saved custody wallets and cash movements that do not touch broker equity."""

from alembic import op

revision = "0014_wallets"
down_revision = "0013_portals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS custody_wallets (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            fund_id UUID NOT NULL REFERENCES funds(id),
            investor_id UUID REFERENCES investors(id),
            owner VARCHAR(16) NOT NULL,
            label VARCHAR(80) NOT NULL,
            address VARCHAR(128) NOT NULL,
            currency VARCHAR(8) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (fund_id, address)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_custody_wallets_organization_id ON custody_wallets (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_custody_wallets_fund_id ON custody_wallets (fund_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_custody_wallets_investor_id ON custody_wallets (investor_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_movements (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            fund_id UUID NOT NULL REFERENCES funds(id),
            wallet_id UUID NOT NULL REFERENCES custody_wallets(id),
            direction VARCHAR(16) NOT NULL,
            amount NUMERIC(20, 8) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            note VARCHAR(240) NOT NULL DEFAULT '',
            actor_user_id UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_wallet_movements_fund_id ON wallet_movements (fund_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wallet_movements_wallet_id ON wallet_movements (wallet_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_movements")
    op.execute("DROP TABLE IF EXISTS custody_wallets")
