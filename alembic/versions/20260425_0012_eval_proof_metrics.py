"""Add eval proof metrics.

Revision ID: 20260425_0012
Revises: 20260411_0011
Create Date: 2026-04-25 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260425_0012"
down_revision = "20260411_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column(
            "average_citation_accuracy",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "eval_runs",
        sa.Column(
            "average_stale_context_detection",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "eval_runs",
        sa.Column(
            "average_naive_answer_correctness",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "eval_runs",
        sa.Column(
            "average_context_answer_lift",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "eval_case_results",
        sa.Column(
            "citation_accuracy",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "eval_case_results",
        sa.Column(
            "stale_context_detection",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "eval_case_results",
        sa.Column(
            "naive_answer_correctness",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "eval_case_results",
        sa.Column(
            "context_answer_lift",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("eval_case_results", "context_answer_lift")
    op.drop_column("eval_case_results", "naive_answer_correctness")
    op.drop_column("eval_case_results", "stale_context_detection")
    op.drop_column("eval_case_results", "citation_accuracy")
    op.drop_column("eval_runs", "average_context_answer_lift")
    op.drop_column("eval_runs", "average_naive_answer_correctness")
    op.drop_column("eval_runs", "average_stale_context_detection")
    op.drop_column("eval_runs", "average_citation_accuracy")
