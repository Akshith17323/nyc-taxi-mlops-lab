"""The MCP server's database user (decision 018): lab_ro reads marts and nothing else.

`password disable`: it never logs in with a password; the MCP server gets temporary credentials through
the Data API's --db-user path, as LabRole. Grants on existing tables survive the mart's refresh (it
deletes and inserts); default privileges cover marts tables created later.
"""

import dagster as dg

from ..resources import RedshiftData

USER = "lab_ro"


@dg.asset(group_name="mcp", deps=["zone_hour_stats"], pool="redshift", kinds={"redshift"})
def mcp_reader(context: dg.AssetExecutionContext, redshift: RedshiftData) -> dg.MaterializeResult:
    exists = redshift.scalar(f"select count(*) from pg_user where usename = '{USER}'")
    statements = [] if exists else [f"create user {USER} password disable"]
    statements += [
        f"grant usage on schema marts to {USER}",
        f"grant select on all tables in schema marts to {USER}",
        f"alter default privileges in schema marts grant select on tables to {USER}",
        f"revoke all on schema ingest from {USER}",
        f"revoke all on schema staging from {USER}",
    ]
    redshift.execute(*statements)
    context.log.info(f"{USER}: {'created' if not exists else 'exists'}, reads marts only")
    return dg.MaterializeResult(metadata={"user": USER, "created": not exists})


# scripts/dagster-run.sh mcp_reader_job --wait
mcp_reader_job = dg.define_asset_job("mcp_reader_job", selection=[mcp_reader])
