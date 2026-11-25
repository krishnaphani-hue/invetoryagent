"""initial schema: machines, snapshots, 4 section tables, current_* views

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SECTIONS = {
    # table: snapshot count column
    "installed_software": "software_count",
    "listening_ports": "port_count",
    "processes": "process_count",
    "services": "service_count",
}


def _child_cols():
    return [
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("snapshot_id", UUID(as_uuid=True), sa.ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("machine_id", UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True),
    ]


def upgrade() -> None:
    op.create_table(
        "machines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("hostname", sa.Text),
        sa.Column("os", sa.Text),
        sa.Column("owner_id", UUID(as_uuid=True), index=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.Column("extra", JSONB),
    )
    op.create_table(
        "snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("machine_id", UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("filename", sa.Text),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("software_count", sa.Integer),
        sa.Column("port_count", sa.Integer),
        sa.Column("process_count", sa.Integer),
        sa.Column("service_count", sa.Integer),
        sa.Column("extra", JSONB),
    )
    op.create_index("ix_snapshots_machine_collected", "snapshots", ["machine_id", sa.text("collected_at DESC")])
    op.create_index("ix_snapshots_received", "snapshots", [sa.text("received_at DESC")])

    op.create_table(
        "installed_software", *_child_cols(),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Text),
        sa.Column("publisher", sa.Text),
        sa.Column("extra", JSONB),
    )
    op.create_table(
        "listening_ports", *_child_cols(),
        sa.Column("protocol", sa.Text),
        sa.Column("local_address", sa.Text),
        sa.Column("port", sa.Integer, nullable=False),
        sa.Column("pid", sa.Integer),
        sa.Column("process_name", sa.Text),
        sa.Column("path", sa.Text),
        sa.Column("version", sa.Text),
        sa.Column("extra", JSONB),
    )
    op.create_table(
        "processes", *_child_cols(),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("pid", sa.Integer),
        sa.Column("path", sa.Text),
        sa.Column("version", sa.Text),
        sa.Column("extra", JSONB),
    )
    op.create_table(
        "services", *_child_cols(),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text),
        sa.Column("status", sa.Text),
        sa.Column("start_type", sa.Text),
        sa.Column("extra", JSONB),
    )

    # Convenience views for pgAdmin / ad-hoc SQL: each machine's current rows per section.
    for table, count_col in SECTIONS.items():
        op.execute(f"""
            CREATE VIEW current_{table} AS
            SELECT t.* FROM {table} t
            JOIN (
                SELECT DISTINCT ON (machine_id) id
                FROM snapshots
                WHERE {count_col} IS NOT NULL
                ORDER BY machine_id, collected_at DESC, received_at DESC
            ) cur ON cur.id = t.snapshot_id
        """)


def downgrade() -> None:
    for table in SECTIONS:
        op.execute(f"DROP VIEW IF EXISTS current_{table}")
    for table in ("services", "processes", "listening_ports", "installed_software", "snapshots", "machines"):
        op.drop_table(table)
