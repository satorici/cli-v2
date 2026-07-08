# Satori CLI

## Install

### From GitHub

```
pip install git+https://github.com/satorici/cli-v2
```

And use the CLI via `satori-v2` command.

> The console script is installed as `satori-v2` to coexist with the v1 CLI.

### From local repository

You'll need pdm to install dependencies and run inside a virtual environment.

```
git clone https://github.com/satorici/cli-v2
cd cli-v2
pdm install
pdm run satori-v2
```

This method does not place a `satori-v2` command in your `PATH`, you must be in the
repository directory to use the CLI.

## Authentication

Set your API token:

```
satori-v2 config token YOUR_TOKEN
```

Use `--profile` to store tokens for different profiles (default is `default`).

To verify, run:

```
satori-v2 config
```

It will display your current configuration, token included.

## Commands

Running `satori-v2` with no subcommand lists your jobs (dashboard). Use `--public` to list public jobs.

| Command | Description |
| --- | --- |
| *(default)* | List jobs (dashboard); supports `--page`, `--quantity`, `--public`, `--json` |
| `jobs` | List jobs (paginated); alias of the default action |
| `config [key] [value]` | View or set config values for a profile |
| `local` | Run a playbook locally against the Satori API |
| `run` | Submit and run a playbook job remotely |
| `scan` | Start a repository scan job |
| `scans` | List scan jobs (paginated) |
| `monitor` | Create a monitor job with a cron expression |
| `monitors` | List monitor jobs (paginated) |
| `job` | Show job details and last 5 executions |
| `execution` | Group for execution management (see subcommands below) |
| `reports` | List executions/reports with filters |
| `report` | Show a single execution report |
| `stop` | Group for stopping runs (see subcommands below) |
| `search` | Search executions; supports bulk download/stop/delete |
| `update` | Reinstall the CLI from GitHub via pip |
| `output` | Show or stream raw output for an execution |
| `shell` | Open an interactive SSH shell for an execution or new session |

### `execution` subcommands

| Subcommand | Description |
| --- | --- |
| `execution get <execution-id>` | Show execution details |
| `execution list` | List executions (paginated) |
| `execution delete <execution-id>` | Delete an execution |
| `execution stop <execution-id>` | Cancel a running execution |
| `execution output <execution-id>` | Show execution output |
| `execution files <execution-id>` | Download execution files |

### `stop` subcommands

| Subcommand | Description |
| --- | --- |
| `stop run <run-id>` | Stop a specific run |
| `stop all` | Stop all queued and running runs |
