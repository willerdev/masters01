"""Organization profile collected during first-run setup."""

from alembic import op

revision = "0003_setup"
down_revision = "0002_step3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS country VARCHAR(80) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS language VARCHAR(16) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS phone_country_code VARCHAR(8) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS phone_number VARCHAR(32) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS admin_email VARCHAR(320) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS setup_completed_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS setup_completed_at")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS admin_email")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS phone_number")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS phone_country_code")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS language")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS country")
