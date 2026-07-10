"""init schema

Revision ID: 001
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(255), unique=True, index=True),
        sa.Column("source", sa.String(64), index=True),
        sa.Column("title", sa.String(512)),
        sa.Column("description", sa.Text()),
        sa.Column("url", sa.String(1024)),
        sa.Column("budget_text", sa.String(128)),
        sa.Column("budget_min_rub", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(64), index=True),
        sa.Column("match_score", sa.Float()),
        sa.Column("match_reasons", sa.Text()),
        sa.Column("suggested_case_slug", sa.String(64)),
        sa.Column("status", sa.Enum("NEW", "MATCHED", "IGNORED", "DRAFTED", "NOTIFIED", "APPROVED", "SENT", "SKIPPED", "CLIENT_REPLIED", name="orderstatus")),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_json", sa.Text()),
        sa.Column("contact_hint", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), index=True),
        sa.Column("text", sa.Text()),
        sa.Column("llm_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "order_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), index=True),
        sa.Column("action", sa.String(32)),
        sa.Column("meta_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "channel_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(128), unique=True),
        sa.Column("last_seen_id", sa.String(128)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "analytics_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.String(10), unique=True, index=True),
        sa.Column("seen", sa.Integer()),
        sa.Column("matched", sa.Integer()),
        sa.Column("notified", sa.Integer()),
        sa.Column("approved", sa.Integer()),
        sa.Column("sent", sa.Integer()),
        sa.Column("skipped", sa.Integer()),
        sa.Column("client_replied", sa.Integer()),
    )


def downgrade() -> None:
    op.drop_table("analytics_daily")
    op.drop_table("channel_states")
    op.drop_table("order_actions")
    op.drop_table("drafts")
    op.drop_table("orders")
