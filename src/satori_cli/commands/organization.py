import rich_click as click
from rich.table import Table

from ..api import client
from ..config import config
from ..utils.console import stdout
from ..utils.groups import IdGroup
from ..utils.options import profile_opt

ROLES = ["OWNER", "ADMIN", "MEMBER"]
role_choice = click.Choice(ROLES, case_sensitive=False)


def _organizations_table(organizations: list[dict]) -> Table:
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Plan")
    table.add_column("Your role")
    for org in organizations:
        table.add_row(str(org["id"]), org["name"], org["plan"], org["role"])
    return table


@click.group(invoke_without_command=True)
@click.pass_context
def organizations(ctx):
    """Organizations you are a member of. Commands act on one with
    `organization ID use`, `--org ID` or SATORI_ORGANIZATION, on your own
    account otherwise."""
    if ctx.invoked_subcommand is None:
        stdout.print(_organizations_table(client.get("/organizations").json()))


@organizations.command(name="create")
@click.argument("name")
def organizations_create(name: str):
    """Create the organization NAME, you are its OWNER (ENTERPRISE plan only)"""
    org = client.post("/organizations", json={"name": name}).json()
    stdout.print(f"Organization {org['id']} created")
    stdout.print(f"Use it with: satori-v2 organization {org['id']} use")


@organizations.command(name="personal")
@profile_opt
def organizations_personal(profile: str):
    """Act on your own account again instead of an organization"""
    config.save("organization", "null", profile)
    stdout.print("Using your own account")


@click.group(cls=IdGroup, invoke_without_command=True)
@click.pass_context
def organization(ctx):
    """Show the organization ORGANIZATION-ID, or manage it with a subcommand"""
    if ctx.invoked_subcommand is None:
        if ctx.obj is None:
            raise click.UsageError("Missing argument 'ORGANIZATION-ID'.")
        org = client.get(f"/organizations/{ctx.obj}").json()
        stdout.print(_organizations_table([org]))


@organization.command(name="use")
@profile_opt
@click.pass_obj
def organization_use(organization_id: int, profile: str):
    """Act on this organization in the following commands"""
    client.get(f"/organizations/{organization_id}")
    config.save("organization", str(organization_id), profile)
    stdout.print(f"Using organization {organization_id}")


@organization.command(name="rename")
@click.argument("name")
@click.pass_obj
def organization_rename(organization_id: int, name: str):
    """Rename the organization to NAME"""
    client.patch(f"/organizations/{organization_id}", json={"name": name})
    stdout.print(f"Organization {organization_id} renamed")


@organization.command(name="delete")
@click.confirmation_option(
    prompt="Delete the organization and all of its jobs, reports and findings?"
)
@click.pass_obj
def organization_delete(organization_id: int):
    """Delete the organization and everything of it (OWNER only)"""
    client.delete(f"/organizations/{organization_id}")
    stdout.print(f"Organization {organization_id} deleted")


@organization.command(name="members")
@click.pass_obj
def organization_members(organization_id: int):
    """List the members and their roles"""
    table = Table(show_header=True, header_style="bold")
    table.add_column("User ID")
    table.add_column("Name")
    table.add_column("Email")
    table.add_column("Role")
    for member in client.get(f"/organizations/{organization_id}/members").json():
        table.add_row(
            str(member["user_id"]),
            member["name"] or "",
            member["email"] or "",
            member["role"],
        )
    stdout.print(table)


@organization.command(name="add")
@click.argument("email")
@click.option("--role", type=role_choice, default="MEMBER", show_default=True)
@click.pass_obj
def organization_add(organization_id: int, email: str, role: str):
    """Add the user with EMAIL, who must have logged in to Satori"""
    member = client.post(
        f"/organizations/{organization_id}/members",
        json={"email": email, "role": role.upper()},
    ).json()
    stdout.print(f"User {member['user_id']} added as {member['role']}")


@organization.command(name="role")
@click.argument("user_id", type=int)
@click.argument("role", type=role_choice)
@click.pass_obj
def organization_role(organization_id: int, user_id: int, role: str):
    """Change the role of the member USER_ID"""
    client.patch(
        f"/organizations/{organization_id}/members/{user_id}",
        json={"role": role.upper()},
    )
    stdout.print(f"User {user_id} is now {role.upper()}")


@organization.command(name="remove")
@click.argument("user_id", type=int)
@click.pass_obj
def organization_remove(organization_id: int, user_id: int):
    """Remove the member USER_ID, or leave the organization with your own id"""
    client.delete(f"/organizations/{organization_id}/members/{user_id}")
    stdout.print(f"User {user_id} removed")
