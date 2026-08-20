"""Add integrity columns, normalized answers, and audit logs."""

from alembic import op
import sqlalchemy as sa

from app.scoring import answer_score

revision = "20260820_02"
down_revision = "20260818_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    duplicates = bind.execute(
        sa.text(
            "SELECT analysis_id, COUNT(*) AS n FROM demo_forms GROUP BY analysis_id HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if duplicates:
        listing = ", ".join(f"{row[0]} x{row[1]}" for row in duplicates)
        raise RuntimeError(
            "analysis_id unique constraint cannot be applied because duplicates exist: "
            f"{listing}. Resolve or merge these rows manually; this migration does not delete them."
        )

    columns = {column["name"] for column in inspector.get_columns("demo_forms")}
    if "deleted_at" not in columns or "possible_duplicate" not in columns:
        with op.batch_alter_table("demo_forms") as batch:
            if "deleted_at" not in columns:
                batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
                batch.create_index("ix_demo_forms_deleted_at", ["deleted_at"])
            if "possible_duplicate" not in columns:
                batch.add_column(
                    sa.Column("possible_duplicate", sa.Boolean(), nullable=False, server_default=sa.false())
                )

    inspector = sa.inspect(bind)
    unique_names = {item["name"] for item in inspector.get_unique_constraints("demo_forms")}
    index_names = {item["name"] for item in inspector.get_indexes("demo_forms")}
    has_unique_analysis = "uq_demo_forms_analysis_id" in unique_names or "uq_demo_forms_analysis_id" in index_names
    has_unique_analysis = has_unique_analysis or any(
        bool(item.get("unique")) and item.get("column_names") == ["analysis_id"]
        for item in inspector.get_indexes("demo_forms")
    )
    if not has_unique_analysis:
        with op.batch_alter_table("demo_forms") as batch:
            batch.create_unique_constraint("uq_demo_forms_analysis_id", ["analysis_id"])

    tables = inspector.get_table_names()
    if "form_answers" not in tables:
        op.create_table(
            "form_answers",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("form_id", sa.Integer(), nullable=False),
            sa.Column("question_no", sa.Integer(), nullable=False),
            sa.Column("value", sa.String(length=32), nullable=True),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["form_id"], ["demo_forms.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("form_id", "question_no", name="uq_form_answers_form_question"),
        )
        op.create_index("ix_form_answers_form_id", "form_answers", ["form_id"])

    if "audit_logs" not in tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("form_id", sa.Integer(), nullable=True),
            sa.Column("analysis_id", sa.String(length=64), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
        op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
        op.create_index("ix_audit_logs_form_id", "audit_logs", ["form_id"])

    existing_answers = bind.execute(sa.text("SELECT COUNT(*) FROM form_answers")).scalar() or 0
    if existing_answers:
        return

    forms = bind.execute(sa.text("SELECT id, answers_json FROM demo_forms")).mappings().all()
    insert_answer = sa.text(
        "INSERT INTO form_answers (form_id, question_no, value, score, status, source) "
        "VALUES (:form_id, :question_no, :value, :score, :status, :source)"
    )
    for form in forms:
        answers = form["answers_json"] or []
        if isinstance(answers, str):
            import json

            answers = json.loads(answers)
        for answer in answers:
            value = answer.get("value")
            status = str(answer.get("status") or "OK")
            bind.execute(
                insert_answer,
                {
                    "form_id": form["id"],
                    "question_no": int(answer.get("questionNo") or answer.get("question_no") or 0),
                    "value": value,
                    "score": answer_score(value, status),
                    "status": status,
                    "source": str(answer.get("source") or "AUTO"),
                },
            )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_form_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_form_answers_form_id", table_name="form_answers")
    op.drop_table("form_answers")
    with op.batch_alter_table("demo_forms") as batch:
        batch.drop_index("ix_demo_forms_deleted_at")
        batch.drop_column("possible_duplicate")
        batch.drop_column("deleted_at")
