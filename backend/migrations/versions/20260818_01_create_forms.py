"""Create the initial form storage schema."""

from alembic import op
import sqlalchemy as sa


revision = "20260818_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "demo_forms" in inspector.get_table_names():
        return
    op.create_table(
        "demo_forms",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("analysis_id", sa.String(length=64), nullable=False),
        sa.Column("template_code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("form_confidence", sa.Float(), nullable=False),
        sa.Column("blank_count", sa.Integer(), nullable=False),
        sa.Column("manual_count", sa.Integer(), nullable=False),
        sa.Column("answers_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", name="uq_demo_forms_analysis_id"),
    )
    op.create_index("ix_demo_forms_created_at", "demo_forms", ["created_at"])
    op.create_index("ix_demo_forms_template_code", "demo_forms", ["template_code"])


def downgrade() -> None:
    op.drop_index("ix_demo_forms_template_code", table_name="demo_forms")
    op.drop_index("ix_demo_forms_created_at", table_name="demo_forms")
    op.drop_table("demo_forms")
