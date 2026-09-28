"""Copy links and any tables added after the initial schema."""

from alembic import op

revision = "0002_step3"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS copy_decisions")
    op.execute("DROP TABLE IF EXISTS copy_links")
