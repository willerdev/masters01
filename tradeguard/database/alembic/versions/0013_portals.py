"""Qualification applications, capital requests, and a firm join code."""

from alembic import op

revision = "0013_portals"
down_revision = "0012_funds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS join_code VARCHAR(32)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_organizations_join_code ON organizations (join_code) WHERE join_code IS NOT NULL")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS qualification_applications (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            user_id UUID NOT NULL REFERENCES users(id),
            kind VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            answers JSON NOT NULL DEFAULT '{}',
            review_note VARCHAR(500) NOT NULL DEFAULT '',
            reviewed_by UUID REFERENCES users(id),
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS capital_requests (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            user_id UUID NOT NULL REFERENCES users(id),
            fund_id UUID NOT NULL REFERENCES funds(id),
            kind VARCHAR(16) NOT NULL,
            amount NUMERIC(20, 8) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            review_note VARCHAR(500) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_applications_org ON qualification_applications (organization_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_capital_requests_org ON capital_requests (organization_id, status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS capital_requests")
    op.execute("DROP TABLE IF EXISTS qualification_applications")
    op.execute("DROP INDEX IF EXISTS ix_organizations_join_code")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS join_code")
