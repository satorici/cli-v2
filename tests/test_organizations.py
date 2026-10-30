from click.testing import CliRunner

from satori_cli.commands.organization import organization, organizations

ORG = {"id": 7, "name": "Acme", "plan": "ENTERPRISE", "role": "OWNER"}


class _FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload

    def json(self):
        return self._payload


def _record(monkeypatch, method: str, payload=None) -> list:
    requests = []

    def call(path, **kwargs):
        requests.append((path, kwargs.get("json")))
        return _FakeResponse(payload)

    monkeypatch.setattr(f"satori_cli.commands.organization.client.{method}", call)
    return requests


def _printed(monkeypatch) -> list:
    printed = []
    monkeypatch.setattr(
        "satori_cli.commands.organization.stdout.print",
        lambda *args, **kwargs: printed.append(args[0] if args else None),
    )
    return printed


def _saved(monkeypatch) -> list:
    saved = []
    monkeypatch.setattr(
        "satori_cli.commands.organization.config.save",
        lambda key, value, profile: saved.append((key, value, profile)),
    )
    return saved


def test_organizations_list(monkeypatch):
    requests = _record(monkeypatch, "get", [ORG])
    printed = _printed(monkeypatch)

    result = CliRunner().invoke(organizations, [])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations", None)]
    table = printed[0]
    assert list(table.columns[0]._cells) == ["7"]
    assert list(table.columns[1]._cells) == ["Acme"]
    assert list(table.columns[3]._cells) == ["OWNER"]


def test_organizations_create(monkeypatch):
    requests = _record(monkeypatch, "post", ORG)
    _printed(monkeypatch)

    result = CliRunner().invoke(organizations, ["create", "Acme"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations", {"name": "Acme"})]


def test_organizations_personal(monkeypatch):
    saved = _saved(monkeypatch)
    _printed(monkeypatch)

    result = CliRunner().invoke(organizations, ["personal"])

    assert result.exit_code == 0, result.output
    assert saved == [("organization", "null", "default")]


def test_organization_show(monkeypatch):
    requests = _record(monkeypatch, "get", ORG)
    printed = _printed(monkeypatch)

    result = CliRunner().invoke(organization, ["7"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations/7", None)]
    assert list(printed[0].columns[1]._cells) == ["Acme"]


def test_organization_requires_an_id(monkeypatch):
    result = CliRunner().invoke(organization, [])

    assert result.exit_code != 0


def test_organization_use(monkeypatch):
    requests = _record(monkeypatch, "get", ORG)
    saved = _saved(monkeypatch)
    _printed(monkeypatch)

    result = CliRunner().invoke(organization, ["7", "use", "--profile", "work"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations/7", None)]
    assert saved == [("organization", "7", "work")]


def test_organization_rename(monkeypatch):
    requests = _record(monkeypatch, "patch", ORG)
    _printed(monkeypatch)

    result = CliRunner().invoke(organization, ["7", "rename", "New"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations/7", {"name": "New"})]


def test_organization_delete_asks_for_confirmation(monkeypatch):
    requests = _record(monkeypatch, "delete")
    _printed(monkeypatch)

    result = CliRunner().invoke(organization, ["7", "delete"], input="n\n")

    assert result.exit_code != 0
    assert requests == []


def test_organization_delete(monkeypatch):
    requests = _record(monkeypatch, "delete")
    _printed(monkeypatch)

    result = CliRunner().invoke(organization, ["7", "delete", "--yes"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations/7", None)]


def test_organization_members(monkeypatch):
    member = {"user_id": 3, "name": None, "email": "a@b.c", "role": "ADMIN"}
    requests = _record(monkeypatch, "get", [member])
    printed = _printed(monkeypatch)

    result = CliRunner().invoke(organization, ["7", "members"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations/7/members", None)]
    table = printed[0]
    assert list(table.columns[0]._cells) == ["3"]
    assert list(table.columns[1]._cells) == [""]
    assert list(table.columns[2]._cells) == ["a@b.c"]


def test_organization_add_defaults_to_member(monkeypatch):
    requests = _record(monkeypatch, "post", {"user_id": 3, "role": "MEMBER"})
    _printed(monkeypatch)

    result = CliRunner().invoke(organization, ["7", "add", "a@b.c"])

    assert result.exit_code == 0, result.output
    assert requests == [
        ("/organizations/7/members", {"email": "a@b.c", "role": "MEMBER"})
    ]


def test_organization_add_with_role(monkeypatch):
    requests = _record(monkeypatch, "post", {"user_id": 3, "role": "ADMIN"})
    _printed(monkeypatch)

    result = CliRunner().invoke(organization, ["7", "add", "a@b.c", "--role", "admin"])

    assert result.exit_code == 0, result.output
    assert requests == [
        ("/organizations/7/members", {"email": "a@b.c", "role": "ADMIN"})
    ]


def test_organization_role(monkeypatch):
    requests = _record(monkeypatch, "patch")
    _printed(monkeypatch)

    result = CliRunner().invoke(organization, ["7", "role", "3", "owner"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations/7/members/3", {"role": "OWNER"})]


def test_organization_role_rejects_unknown_roles(monkeypatch):
    requests = _record(monkeypatch, "patch")

    result = CliRunner().invoke(organization, ["7", "role", "3", "BOSS"])

    assert result.exit_code != 0
    assert requests == []


def test_organization_remove(monkeypatch):
    requests = _record(monkeypatch, "delete")
    _printed(monkeypatch)

    result = CliRunner().invoke(organization, ["7", "remove", "3"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations/7/members/3", None)]
