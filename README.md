# Satori CLI

## Install

### From GitHub

```
pip install git+https://github.com/satorici/cli-v2
```

And use the CLI via `satori` command.

### From local repository

You'll need pdm to install dependencies and run inside a virtual environment.

```
git clone https://github.com/satorici/cli-v2
cd cli-v2
pdm install
pdm run satori
```

This method does not place a `satori` command in your `PATH`, you must be in the
repository directory to use the CLI.

## Authentication

Run this command:

```
satori login
```

Visit the URL displayed, where you can login using GitHub. After that, return to
the terminal and you should see a login confirmation. To verify, run:

```
satori config
```

It will display your current configuration, token included.
