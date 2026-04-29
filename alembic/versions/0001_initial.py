"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), unique=True, nullable=True),
        sa.Column("phone", sa.String(15), unique=True, nullable=True),
        sa.Column("email", sa.String(255), unique=True, nullable=True),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("broker", sa.String(20), nullable=True),
        sa.Column("broker_token_enc", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    plan_enum = sa.Enum("free", "basic", "premium", "elite", name="plan_enum")
    plan_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan", plan_enum, nullable=False, server_default="free"),
        sa.Column("razorpay_subscription_id", sa.String(64), nullable=True),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])

    segment_enum = sa.Enum(
        "equity", "fut_idx", "opt_idx", "fut_stk", "opt_stk", "currency", "commodity",
        name="segment_enum",
    )
    segment_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "instruments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kite_token", sa.BigInteger(), unique=True, nullable=False),
        sa.Column("tradingsymbol", sa.String(64), nullable=False),
        sa.Column("exchange", sa.String(8), nullable=False),
        sa.Column("segment", segment_enum, nullable=False),
        sa.Column("lot_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tick_size", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instruments_tradingsymbol", "instruments", ["tradingsymbol"])
    op.create_index("ix_instruments_kite_token", "instruments", ["kite_token"])

    op.create_table(
        "ticks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kite_token", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("ts_ist", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("bid", sa.Float(), nullable=True),
        sa.Column("ask", sa.Float(), nullable=True),
        sa.Column("bid_qty", sa.Integer(), nullable=True),
        sa.Column("ask_qty", sa.Integer(), nullable=True),
    )
    op.create_index("ix_ticks_kite_token", "ticks", ["kite_token"])
    op.create_index("ix_ticks_symbol", "ticks", ["symbol"])
    op.create_index("ix_ticks_ts_ist", "ticks", ["ts_ist"])

    side_enum = sa.Enum("BUY", "SELL", name="signal_side_enum")
    side_enum.create(op.get_bind(), checkfirst=True)
    status_enum = sa.Enum(
        "open", "hit_t1", "hit_t2", "hit_sl", "expired", name="signal_status_enum"
    )
    status_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("segment", sa.String(16), nullable=False),
        sa.Column("side", side_enum, nullable=False),
        sa.Column("entry_low", sa.Float(), nullable=False),
        sa.Column("entry_high", sa.Float(), nullable=False),
        sa.Column("target1", sa.Float(), nullable=False),
        sa.Column("target2", sa.Float(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("risk_reward", sa.Float(), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False, server_default="5m"),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("regime", sa.String(16), nullable=False, server_default="UNKNOWN"),
        sa.Column("layers_voted", sa.Integer(), nullable=False),
        sa.Column("layer_breakdown", sa.JSON(), nullable=False),
        sa.Column("status", status_enum, nullable=False, server_default="open"),
        sa.Column("fired_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_signals_symbol", "signals", ["symbol"])
    op.create_index("ix_signals_fired_at", "signals", ["fired_at"])


def downgrade() -> None:
    op.drop_table("signals")
    op.drop_table("ticks")
    op.drop_table("instruments")
    op.drop_table("subscriptions")
    op.drop_table("users")
    for enum_name in (
        "signal_status_enum",
        "signal_side_enum",
        "segment_enum",
        "plan_enum",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
