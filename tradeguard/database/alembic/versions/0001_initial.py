"""Initial TradeGuard schema."""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION tradeguard_audit_immutable()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'audit_logs are immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs;
            CREATE TRIGGER audit_logs_no_update
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION tradeguard_audit_immutable();
            """
        )


def downgrade() -> None:
    from app.models import Base

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS tradeguard_audit_immutable()")
    Base.metadata.drop_all(bind=bind)
