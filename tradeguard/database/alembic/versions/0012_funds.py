"""Fund books, locked NAV, investors, fees, guidelines, and allocations."""

from alembic import op

revision = "0012_funds"
down_revision = "0011_trade_milestones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategies (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            name VARCHAR(160) NOT NULL,
            version VARCHAR(32) NOT NULL DEFAULT '1',
            description VARCHAR(500) NOT NULL DEFAULT '',
            magic_number INTEGER,
            status VARCHAR(24) NOT NULL DEFAULT 'active',
            risk_limit_pct NUMERIC(12, 6) NOT NULL DEFAULT 1,
            daily_loss_pct NUMERIC(12, 6) NOT NULL DEFAULT 3,
            max_positions INTEGER NOT NULL DEFAULT 5,
            allowed_symbols JSON NOT NULL DEFAULT '[]',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, name, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_accounts (
            id UUID PRIMARY KEY,
            strategy_id UUID NOT NULL REFERENCES strategies(id),
            account_id UUID NOT NULL REFERENCES accounts(id),
            UNIQUE (strategy_id, account_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trader_profiles (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            user_id UUID REFERENCES users(id),
            name VARCHAR(160) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'active',
            risk_per_trade_pct NUMERIC(12, 6) NOT NULL DEFAULT 0.5,
            daily_loss_pct NUMERIC(12, 6) NOT NULL DEFAULT 1.5,
            max_positions INTEGER NOT NULL DEFAULT 5,
            max_trades_per_day INTEGER NOT NULL DEFAULT 10,
            max_drawdown_pct NUMERIC(12, 6) NOT NULL DEFAULT 5,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trader_accounts (
            id UUID PRIMARY KEY,
            trader_id UUID NOT NULL REFERENCES trader_profiles(id),
            account_id UUID NOT NULL REFERENCES accounts(id),
            UNIQUE (trader_id, account_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_budgets (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            scope_type VARCHAR(24) NOT NULL,
            scope_key VARCHAR(80) NOT NULL,
            label VARCHAR(160) NOT NULL DEFAULT '',
            max_daily_risk_pct NUMERIC(12, 6) NOT NULL,
            allocated_pct NUMERIC(12, 6) NOT NULL DEFAULT 0,
            reserved_pct NUMERIC(12, 6) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, scope_type, scope_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS funds (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            name VARCHAR(160) NOT NULL,
            base_currency VARCHAR(8) NOT NULL DEFAULT 'USD',
            status VARCHAR(24) NOT NULL DEFAULT 'open',
            management_fee_pct NUMERIC(12, 6) NOT NULL DEFAULT 0,
            performance_fee_pct NUMERIC(12, 6) NOT NULL DEFAULT 0,
            crystallization VARCHAR(16) NOT NULL DEFAULT 'quarterly',
            high_water_mark NUMERIC(20, 8) NOT NULL DEFAULT 1,
            unit_price NUMERIC(20, 8) NOT NULL DEFAULT 1,
            units_outstanding NUMERIC(28, 8) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_books (
            id UUID PRIMARY KEY,
            fund_id UUID NOT NULL REFERENCES funds(id),
            name VARCHAR(160) NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_book_accounts (
            id UUID PRIMARY KEY,
            book_id UUID NOT NULL REFERENCES fund_books(id),
            account_id UUID NOT NULL REFERENCES accounts(id),
            UNIQUE (book_id, account_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS investors (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            user_id UUID REFERENCES users(id),
            name VARCHAR(160) NOT NULL,
            email VARCHAR(320) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, email)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS investor_holdings (
            id UUID PRIMARY KEY,
            fund_id UUID NOT NULL REFERENCES funds(id),
            investor_id UUID NOT NULL REFERENCES investors(id),
            units NUMERIC(28, 8) NOT NULL DEFAULT 0,
            high_water_mark NUMERIC(20, 8) NOT NULL DEFAULT 1,
            capital_paid NUMERIC(20, 8) NOT NULL DEFAULT 0,
            UNIQUE (fund_id, investor_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS capital_movements (
            id UUID PRIMARY KEY,
            holding_id UUID NOT NULL REFERENCES investor_holdings(id),
            kind VARCHAR(16) NOT NULL,
            amount NUMERIC(20, 8) NOT NULL,
            units NUMERIC(28, 8) NOT NULL,
            unit_price NUMERIC(20, 8) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS nav_records (
            id UUID PRIMARY KEY,
            fund_id UUID NOT NULL REFERENCES funds(id),
            as_of TIMESTAMPTZ NOT NULL,
            aum NUMERIC(20, 8) NOT NULL,
            unit_price NUMERIC(20, 8) NOT NULL,
            units_outstanding NUMERIC(28, 8) NOT NULL,
            high_water_mark NUMERIC(20, 8) NOT NULL,
            locked BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fee_records (
            id UUID PRIMARY KEY,
            fund_id UUID NOT NULL REFERENCES funds(id),
            holding_id UUID REFERENCES investor_holdings(id),
            kind VARCHAR(24) NOT NULL,
            amount NUMERIC(20, 8) NOT NULL,
            calculation JSON NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_samples (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            account_id UUID NOT NULL REFERENCES accounts(id),
            symbol VARCHAR(64) NOT NULL DEFAULT '',
            requested_price NUMERIC(20, 10),
            executed_price NUMERIC(20, 10),
            slippage NUMERIC(20, 10),
            spread NUMERIC(20, 10),
            latency_ms INTEGER,
            rejected BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reconciliation_events (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            account_id UUID NOT NULL REFERENCES accounts(id),
            status VARCHAR(40) NOT NULL,
            detail JSON NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS desk_rules (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            fund_id UUID REFERENCES funds(id),
            name VARCHAR(160) NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            metric VARCHAR(40) NOT NULL,
            operator VARCHAR(8) NOT NULL,
            threshold NUMERIC(20, 8) NOT NULL,
            action VARCHAR(32) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, name, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_orders (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            fund_id UUID NOT NULL REFERENCES funds(id),
            symbol VARCHAR(64) NOT NULL,
            side VARCHAR(8) NOT NULL,
            order_type VARCHAR(16) NOT NULL,
            volume NUMERIC(18, 8) NOT NULL,
            price NUMERIC(20, 10),
            stop_loss NUMERIC(20, 10),
            take_profit NUMERIC(20, 10),
            status VARCHAR(16) NOT NULL DEFAULT 'rejected',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_allocations (
            id UUID PRIMARY KEY,
            fund_order_id UUID NOT NULL REFERENCES fund_orders(id),
            account_id UUID NOT NULL REFERENCES accounts(id),
            volume NUMERIC(18, 8) NOT NULL,
            sent BOOLEAN NOT NULL DEFAULT FALSE,
            decision VARCHAR(32) NOT NULL DEFAULT '',
            message VARCHAR(400) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_funds_org ON funds (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_nav_fund ON nav_records (fund_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_fund_orders_fund ON fund_orders (fund_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fund_allocations")
    op.execute("DROP TABLE IF EXISTS fund_orders")
    op.execute("DROP TABLE IF EXISTS desk_rules")
    op.execute("DROP TABLE IF EXISTS reconciliation_events")
    op.execute("DROP TABLE IF EXISTS execution_samples")
    op.execute("DROP TABLE IF EXISTS fee_records")
    op.execute("DROP TABLE IF EXISTS nav_records")
    op.execute("DROP TABLE IF EXISTS capital_movements")
    op.execute("DROP TABLE IF EXISTS investor_holdings")
    op.execute("DROP TABLE IF EXISTS investors")
    op.execute("DROP TABLE IF EXISTS fund_book_accounts")
    op.execute("DROP TABLE IF EXISTS fund_books")
    op.execute("DROP TABLE IF EXISTS funds")
    op.execute("DROP TABLE IF EXISTS risk_budgets")
    op.execute("DROP TABLE IF EXISTS trader_accounts")
    op.execute("DROP TABLE IF EXISTS trader_profiles")
    op.execute("DROP TABLE IF EXISTS strategy_accounts")
    op.execute("DROP TABLE IF EXISTS strategies")
