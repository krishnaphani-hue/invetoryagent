"""threat intelligence: CVE matches for installed software, version-range cache

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "threat_matches",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("software_name", sa.Text, nullable=False),
        sa.Column("software_version", sa.Text, nullable=False, server_default=""),
        sa.Column("cve_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("match_token", sa.Text),
        sa.Column("vendor", sa.Text),
        sa.Column("product", sa.Text),
        sa.Column("vulnerable_range", sa.Text),
        sa.Column("fixed_version", sa.Text),
        sa.Column("severity", sa.Text),
        sa.Column("cvss_v3", sa.Float),
        sa.Column("epss", sa.Float),
        sa.Column("is_cisa_kev", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_public_poc", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_metasploit", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_nuclei", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("ai_summary", sa.Text),
        sa.Column("matched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("software_name", "software_version", "cve_id", name="uq_threat_matches_software_cve"),
    )
    op.create_index("ix_threat_matches_software", "threat_matches", ["software_name", "software_version"])
    op.create_index("ix_threat_matches_cve", "threat_matches", ["cve_id"])

    op.create_table(
        "threat_cve_ranges",
        sa.Column("cve_id", sa.Text, primary_key=True),
        sa.Column("ranges", JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("threat_cve_ranges")
    op.drop_index("ix_threat_matches_cve", table_name="threat_matches")
    op.drop_index("ix_threat_matches_software", table_name="threat_matches")
    op.drop_table("threat_matches")
