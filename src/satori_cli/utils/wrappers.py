import json
import sys
from datetime import datetime, timedelta
from itertools import groupby
from math import floor
from typing import Generic, TypeVar

from rich.console import Console, ConsoleOptions, RenderResult
from rich.highlighter import RegexHighlighter
from rich.panel import Panel
from rich.segment import Segment
from rich.table import Column, Table

if sys.version_info < (3, 11):
    from typing_extensions import TypedDict
else:
    from typing import TypedDict

from ..utils.format import is_json_output

T = TypeVar("T")


class Wrapper(Generic[T]):
    def __init__(self, obj: T):
        self.obj = obj

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        raise NotImplementedError


W = TypeVar("W", bound=Wrapper)


def has_json_output(cls: type[W]):
    orig = cls.__rich_console__

    def __rich_console__(self: W, console: Console, options: ConsoleOptions):
        if is_json_output():
            console.out(json.dumps(self.obj, indent=2))
        else:
            yield from orig(self, console, options)

    cls.__rich_console__ = __rich_console__

    return cls


def command_generator(job: dict):
    job_type: str = job["type"]

    if job_type == "MONITOR":
        return f"satori-v2 run {job['playbook_source']}"

    command = ["satori-v2", job_type.lower(), job["playbook_source"]]

    if job_type == "SCAN":
        command.append(job["repository_data"]["repository"])

    return " ".join(command)


@has_json_output
class JobWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        job = self.obj
        job_type = job["type"]

        job_grid = Table.grid(padding=(0, 2))

        if job_type != "GITHUB":
            job_grid.add_row("Command", command_generator(job))

        job_grid.add_row("Type", job_type.capitalize())
        job_grid.add_row("Playbook source", job["playbook_source"])
        job_grid.add_row("Visibility", job["visibility"].capitalize())
        job_grid.add_row("Created at", ISODateTime(job["created_at"]))

        if status := job.get("status"):
            finished_job = job_type in ("RUN", "SCAN") and status == "FINISHED"

            if finished_job and job["finished_at"]:
                job_grid.add_row("Finished at", ISODateTime(job["finished_at"]))

            job_grid.add_row("Status", status.capitalize().replace("_", " "))

            if finished_job:
                result = highlight_result("Fail" if job["failed_reports"] else "Pass")
            else:
                result = "N/A"

            if job["type"] == "RUN":
                job_grid.add_row("Execution count", str(job["count"]))
                job_grid.add_row("Result", result)

            if job["type"] == "MONITOR":
                job_grid.add_row("Schedule expression", str(job["expression"]))

        if estimated_cost := job.get("estimated_cost"):
            job_grid.add_row("Estimated cost", f"USD {estimated_cost:.6f}")

        yield Panel(job_grid, title=f"Job {job['id']}", title_align="left")


class JobExecutionsWrapper(Wrapper[list]):
    def __rich_console__(self, console, options):
        table = Table(expand=True)
        table.add_column("Report id")
        table.add_column("Created at")
        table.add_column("Region")
        table.add_column("Status")
        table.add_column("Visibility")
        table.add_column("Result")

        for execution in self.obj:
            if report := execution["data"].get("report"):
                result = highlight_result("Fail" if report["fails"] else "Pass")
            else:
                result = "N/A"

            table.add_row(
                str(execution["id"]),
                ISODateTime(execution["created_at"]),
                execution["data"].get("region", "N/A"),
                execution["status"].capitalize().replace("_", " "),
                execution["visibility"].capitalize(),
                result,
            )

        yield table


class JobListWrapper(Wrapper[list]):
    def __rich_console__(self, console, options):
        table = Table(expand=True)
        table.add_column("Id")
        table.add_column("Playbook source")
        table.add_column("Schedule")
        table.add_column("Repository")
        table.add_column("Status")
        table.add_column("Visibility")
        table.add_column("Created at")

        for job in self.obj:
            job_type = job["type"]
            schedule = job.get("expression", "N/A") if job_type == "MONITOR" else "N/A"
            repository = (
                job["repository_data"]["repository"]
                if job_type == "SCAN" and job.get("repository_data")
                else "N/A"
            )

            table.add_row(
                str(job["id"]),
                job["playbook_source"],
                schedule,
                repository,
                job["status"].capitalize().replace("_", " "),
                job["visibility"].capitalize(),
                ISODateTime(job["created_at"]),
            )

        yield table


class SshSessionsListWrapper(Wrapper[list]):
    def __rich_console__(self, console, options):
        table = Table(expand=True)
        table.add_column("Id")
        table.add_column("Status")
        table.add_column("Region")
        table.add_column("Image")
        table.add_column("Host")
        table.add_column("Created at")
        table.add_column("Finished at")

        for session in self.obj:
            region = session.get("region")
            if region is None and session.get("regions"):
                region = ", ".join(session["regions"])

            table.add_row(
                str(session["id"]),
                session["status"].capitalize().replace("_", " "),
                region or "N/A",
                session["container_settings"]["image"],
                session.get("host") or "N/A",
                ISODateTime(session["created_at"]),
                ISODateTime(session["finished_at"])
                if session.get("finished_at")
                else "N/A",
            )

        yield table


def to_datetime(s: str):
    orig = s if s.endswith(("Z", "+00:00")) else s + "Z"

    try:
        return datetime.strptime(orig, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        return datetime.strptime(orig, "%Y-%m-%dT%H:%M:%S%z")


class ISODateTime(Wrapper[str]):
    def __rich_console__(self, console, options):
        yield to_datetime(self.obj).strftime("%Y-%m-%d %H:%M:%S")


class ResultHighlighter(RegexHighlighter):
    highlights = [r"(?P<green>Pass)", r"(?P<red>Fail)"]


highlight_result = ResultHighlighter()


@has_json_output
class ExecutionWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        job = self.obj["job"]
        data = self.obj["data"]
        report = self.obj["report"]

        grid = Table.grid(Column(ratio=1), Column(ratio=1), expand=True)

        execution_grid = Table.grid(padding=(0, 2))
        execution_grid.add_row("Status", self.obj["status"].capitalize())
        execution_grid.add_row("Visibility", self.obj["visibility"].capitalize())

        if region := data.get("region"):
            execution_grid.add_row("Region", region)

        execution_grid.add_row("Created at", ISODateTime(self.obj["created_at"]))

        if started_at := data.get("timestamps", {}).get("startedAt"):
            execution_grid.add_row("Started at", ISODateTime(started_at))
        if stopped_at := data.get("timestamps", {}).get("executionStoppedAt"):
            execution_grid.add_row("Stopped at", ISODateTime(stopped_at))

        job_grid = Table.grid(padding=(0, 2))
        job_grid.add_row("Type", job["type"].capitalize())
        job_grid.add_row("Visibility", job["visibility"].capitalize())
        job_grid.add_row("Created at", ISODateTime(job["created_at"]))
        job_grid.add_row("Playbook source", job["playbook_source"])

        grid.add_row(
            execution_grid,
            Panel(job_grid, title=f"Job {job['id']}", title_align="left"),
        )

        yield Panel(grid, title=f"Execution {self.obj['id']}", title_align="left")

        if report and report.get("detail"):
            yield ReportWrapper(report["detail"])


class PagedResponse(Generic[T], TypedDict):
    total: int
    items: list[T]


@has_json_output
class PagedWrapper(Wrapper[PagedResponse[W]]):
    def __init__(self, obj, page: int, quantity: int, items_wrapper: type[W]):
        self._wrapper = items_wrapper
        self.page = page
        self.quantity = quantity
        super().__init__(obj)

    def __rich_console__(self, console, options):
        yield self._wrapper(self.obj["items"])
        yield f"Page {self.page} of {floor(self.obj['total'] / self.quantity)} | Total: {self.obj['total']}"


class ExecutionListWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        table = Table(expand=True)
        table.add_column("Id")
        table.add_column("Playbook source")
        table.add_column("Parameters")
        table.add_column("Status")
        table.add_column("Visibility")
        table.add_column("Job type")
        table.add_column("Result")
        table.add_column("Run time")
        table.add_column("Created at")

        for execution in self.obj:
            if report := execution["report"]:
                result = highlight_result("Fail" if report["total_fails"] else "Pass")
            else:
                result = "N/A"

            job = execution["job"]

            timestamps: dict[str, int] = execution["data"].get("timestamps", {})
            run_time = "N/A"

            if timestamps.get("execution_started_at") and timestamps.get(
                "execution_finished_at"
            ):
                run_time = str(
                    timedelta(
                        seconds=max(
                            0,
                            timestamps["execution_finished_at"]
                            - timestamps["execution_started_at"],
                        )
                    )
                )

            if job["type"] == "LOCAL" and "results_uploaded_at" in timestamps:
                run_time = str(
                    timedelta(
                        seconds=max(
                            0,
                            timestamps["results_uploaded_at"]
                            - to_datetime(job["created_at"]).timestamp(),
                        )
                    )
                )

            parameters = ""

            if job["parameters"] is not None:
                parameters = " ".join(
                    f"{k}={','.join(v)}" for k, v in job["parameters"].items()
                )

            table.add_row(
                str(execution["id"]),
                job["playbook_source"],
                parameters,
                execution["status"].capitalize().replace("_", " "),
                execution["visibility"].capitalize(),
                job["type"].capitalize(),
                result,
                run_time,
                ISODateTime(execution["created_at"]),
            )

        yield table


@has_json_output
class ReportWrapper(Wrapper[list[dict]]):
    def __rich_console__(self, console, options):
        has_asserts = any(detail.get("asserts") for detail in self.obj)

        if has_asserts:
            table = Table(
                Column("Test", ratio=1),
                Column("Assert", ratio=1),
                Column("Assert value", ratio=1),
                Column("Result", ratio=1),
                expand=True,
            )

            for detail in self.obj:
                check = "✅" if detail["test_status"] == "Pass" else "❌"
                test_name = check + " " + ":".join(detail["test"].split(" > "))
                asserts = detail.get("asserts") or []

                if not asserts:
                    table.add_row(
                        test_name,
                        "",
                        "",
                        highlight_result(detail["test_status"]),
                    )
                    table.add_section()
                    continue

                grouped_asserts = groupby(asserts, lambda x: x["assert"])
                for name, valresults in grouped_asserts:
                    values = list(valresults)
                    expected = "\n".join([str(val["expected"]) for val in values])
                    status = highlight_result(
                        "\n".join([str(val["status"]) for val in values])
                    )

                    table.add_row(test_name, name.lstrip("assert"), expected, status)
                    test_name = ""

                table.add_section()

            yield table
            return

        # No asserts: show the Satori tests summary (mirrors the web Tests tab).
        table = Table(
            Column("Test", ratio=3),
            Column("Status", ratio=1),
            Column("Testcases", ratio=1, justify="right"),
            Column("Fails", ratio=1, justify="right"),
            expand=True,
        )

        for detail in self.obj:
            check = "✅" if detail["test_status"] == "Pass" else "❌"
            test_name = check + " " + ":".join(detail["test"].split(" > "))
            table.add_row(
                test_name,
                highlight_result(detail["test_status"]),
                str(detail.get("testcases", "")),
                str(detail.get("total_fails", "")),
            )

        yield table


FINDING_CAP = 50

_SEVERITY_STYLE = {
    "BLOCKER": "bold red",
    "CRITICAL": "bold red",
    "HIGH": "red",
    "MEDIUM": "yellow",
    "LOW": "cyan",
    "INFO": "dim",
}


def _finding_title(finding) -> str:
    """Prefer a readable title; fall back to description when title is just the id."""
    title = finding.title or ""
    if finding.description and (not title or title == finding.id):
        return finding.description
    return title


def _finding_location(finding) -> str:
    location = finding.location or ""
    if finding.line is not None and location:
        return f"{location}:{finding.line}"
    if finding.line is not None:
        return str(finding.line)
    return location


def _finding_detail(finding) -> str:
    """Secondary detail for the row: description (if not used as title) + key fields."""
    parts: list[str] = []
    title = _finding_title(finding)
    if finding.description and finding.description != title:
        parts.append(finding.description)
    if finding.url:
        parts.append(finding.url)
    # Prefer a few high-signal leftover fields over dumping everything.
    preferred = ("cwe", "remediation", "confidence", "rule", "category")
    extras: list[str] = []
    if finding.fields:
        for key in preferred:
            if key in finding.fields:
                extras.append(f"{key}={finding.fields[key]}")
        if not extras:
            for key, value in list(finding.fields.items())[:2]:
                extras.append(f"{key}={value}")
    if extras:
        parts.append(" · ".join(extras))
    return "\n".join(parts)


class DynamicFindingsWrapper(Wrapper[list[tuple[str, list]]]):
    """Rich display of dynamically parsed findings, grouped by test path.

    ``obj`` is a list of ``(test_path, findings)`` pairs.
    """

    def __rich_console__(self, console, options):
        from .parsers.dynamic import dynamic_severity_to_template

        yield ""
        yield "[b]Parsed findings[/b] [dim](auto)[/dim]"

        for test_path, findings in self.obj:
            visible = findings[:FINDING_CAP]
            table = Table(
                Column("Severity", no_wrap=True),
                Column("Id", no_wrap=True),
                Column("Location", ratio=2, overflow="fold"),
                Column("Finding", ratio=4, overflow="fold"),
                title=test_path,
                title_justify="left",
                expand=True,
                show_lines=True,
            )

            for finding in visible:
                mapped = dynamic_severity_to_template(finding.severity)
                style = _SEVERITY_STYLE.get(mapped or "", "")
                severity = finding.severity or ""
                title = _finding_title(finding)
                detail = _finding_detail(finding)
                finding_cell = title
                if detail:
                    finding_cell = f"{title}\n[dim]{detail}[/dim]"

                table.add_row(
                    f"[{style}]{severity}[/{style}]" if style and severity else severity,
                    finding.id or "",
                    _finding_location(finding),
                    finding_cell,
                )

            yield table

            if len(findings) > FINDING_CAP:
                yield f"[dim]… and {len(findings) - FINDING_CAP} more findings[/dim]"

            yield ""


class OutputWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        output = self.obj
        result = output["output"]

        grid = Table.grid("", "", padding=(0, 2))
        grid.add_row("[green]Command:[/green]", output["original"])

        if result["return_code"] is not None:
            grid.add_row("Return code:", str(result["return_code"]))

        if output["testcase"]:
            testcase = Table(
                Column(style="b"),
                Column(),
                show_header=False,
                show_edge=False,
                pad_edge=False,
            )

            for key, value in output["testcase"].items():
                testcase.add_row(key, value.decode(errors="ignore"))

            grid.add_row("Testcase:", testcase)

        if error := result["os_error"]:
            grid.add_row("Error:", error)

        if result["time"] is not None:
            grid.add_row("Time:", str(timedelta(seconds=result["time"])))

        yield grid

        yield "Stdout:"
        if stdout := result["stdout"]:
            yield Segment(stdout.decode(errors="ignore"))
            yield ""

        yield "Stderr:"
        if stderr := result["stderr"]:
            yield Segment(stderr.decode(errors="ignore"))
            yield ""


@has_json_output
class PlaybookCatalogWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        yield f"[b]Playbooks[/b] ({self.obj['count']}) — synced {self.obj['synced_at']} @ {self.obj['commit'][:7]}"

        table = Table(expand=True)
        table.add_column("Id")
        table.add_column("Name")
        table.add_column("Category")
        table.add_column("Image")
        # table.add_column("Description")

        for playbook in self.obj["playbooks"]:
            table.add_row(
                "satori://" + playbook["id"],
                playbook["name"],
                playbook["category"],
                playbook.get("image") or "",
                # playbook.get("description") or "",
            )

        yield table


@has_json_output
class PlaybookDetailWrapper(Wrapper[dict]):
    def __rich_console__(self, console, options):
        grid = Table.grid("", "", padding=(0, 2))
        grid.add_row("[b]Id[/b]", self.obj["id"])
        grid.add_row("[b]Name[/b]", self.obj["name"])
        grid.add_row("[b]URI[/b]", self.obj["uri"])
        grid.add_row("[b]Category[/b]", self.obj["category"])
        grid.add_row("[b]Image[/b]", self.obj.get("image") or "")
        grid.add_row("[b]Description[/b]", self.obj.get("description") or "")

        if parameters := self.obj.get("parameters"):
            grid.add_row("[b]Parameters[/b]", ", ".join(parameters))

        if authors := self.obj.get("author"):
            grid.add_row("[b]Author[/b]", ", ".join(authors))

        if example := self.obj.get("example"):
            grid.add_row("[b]Example[/b]", example)

        yield grid

        if content := self.obj.get("content"):
            yield Panel(content, title="Content", border_style="dim")
