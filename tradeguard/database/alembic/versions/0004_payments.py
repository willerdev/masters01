"""Payment provider credentials, crypto payments, and tables added with the platform models."""

from alembic import op

revision = "0004_payments"
down_revision = "0003_setup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS plan_code VARCHAR(32) NOT NULL DEFAULT 'enterprise'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS crypto_payments")
    op.execute("DROP TABLE IF EXISTS payment_provider_configs")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS plan_code")
