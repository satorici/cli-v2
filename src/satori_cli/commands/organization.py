import rich_click as click
from rich.table import Table

from ..api import client
from ..config import config
from ..utils.console import stdout
from ..utils.groups import IdGroup
from ..utils.options import profile_opt, resolve_organization

ROLES = ["OWNER", "ADMIN", "MEMBER"]
role_choice = click.Choice(ROLES, case_sensitive=False)


PERSONAL = object()


class OrganizationParam(click.ParamType):
    """An organization ID or name, or `Personal` for your own account"""

    name = "organization"

    def convert(self, value, param, ctx):
        if value.casefold() == "personal":
            return PERSONAL
        return resolve_organization(value)


def _use_personal(profile: str):
    config.save("organization", "null", profile)
    stdout.print("Using your own account")


def _organizations_table(organizations: list[dict], personal: bool = False) -> Table:
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Plan")
    table.add_column("Your role")
    if personal:
        table.add_row("-", "Personal", "-", "-")
    for org in organizations:
        table.add_row(str(org["id"]), org["name"], org["plan"], org["role"])
    return table


@click.group(invoke_without_command=True)
@click.pass_context
def organizations(ctx):
    """Organizations you are a member of. Commands act on one with
    `config organization ID|NAME`, `organization ID use`, `--org ID|NAME` at the
    end of a command or SATORI_ORGANIZATION, on your own account otherwise."""
    if ctx.invoked_subcommand is None:
        stdout.print(
            _organizations_table(client.get("/organizations").json(), personal=True)
        )


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
    _use_personal(profile)


@click.group(
    cls=IdGroup, id_type=OrganizationParam(), invoke_without_command=True
)
@click.pass_context
def organization(ctx):
    """Show the organization ORGANIZATION (ID, name or Personal), or manage it
    with a subcommand"""
    if ctx.obj is PERSONAL and ctx.invoked_subcommand not in (None, "use"):
        raise click.UsageError("Personal is your own account, not an organization")
    if ctx.invoked_subcommand is None:
        if ctx.obj is None:
            raise click.UsageError("Missing argument 'ORGANIZATION'.")
        if ctx.obj is PERSONAL:
            stdout.print(_organizations_table([], personal=True))
            return
        org = client.get(f"/organizations/{ctx.obj}").json()
        stdout.print(_organizations_table([org]))


@organization.command(name="use")
@profile_opt
@click.pass_obj
def organization_use(organization_id, profile: str):
    """Act on this organization in the following commands"""
    if organization_id is PERSONAL:
        _use_personal(profile)
        return
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
@click.argument("email", required=False)
@click.option("--github", metavar="USERNAME", help="Find the user by GitHub username")
@click.option("--role", type=role_choice, default="MEMBER", show_default=True)
@click.pass_obj
def organization_add(
    organization_id: int, email: str | None, github: str | None, role: str
):
    """Add the user with EMAIL or --github USERNAME, who must have logged in to Satori"""
    if (email is None) == (github is None):
        raise click.UsageError("Pass either EMAIL or --github USERNAME")
    who = {"email": email} if github is None else {"github": github}
    member = client.post(
        f"/organizations/{organization_id}/members",
        json={**who, "role": role.upper()},
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
