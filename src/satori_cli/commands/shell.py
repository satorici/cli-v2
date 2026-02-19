import fcntl
import os
import select
import signal
import struct
import sys
import termios
import time
import tty

import paramiko
import rich_click as click
from rich.progress import Progress

from ..api import client
from ..utils import options as opts
from ..utils.misc import remove_none_values


def get_terminal_size():
    buf = fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, b"\x00" * 8)
    rows, cols = struct.unpack("hh", buf[:4])
    return cols, rows


def interactive_shell(host: str, token: str):
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy)
    ssh_client.connect(hostname=host, username="root", password=token)

    cols, rows = get_terminal_size()
    channel = ssh_client.invoke_shell(term="xterm-256color", width=cols, height=rows)

    def resize_handler(signum, frame):
        cols, rows = get_terminal_size()
        channel.resize_pty(width=cols, height=rows)

    old_handler = signal.signal(signal.SIGWINCH, resize_handler)
    old_tty = termios.tcgetattr(sys.stdin)

    try:
        tty.setraw(sys.stdin.fileno())
        channel.settimeout(0.0)

        while True:
            r, _, _ = select.select([channel, sys.stdin], [], [])

            if channel in r:
                try:
                    data = channel.recv(1024)

                    if not data:
                        break

                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                except Exception:
                    break

            if sys.stdin in r:
                data = os.read(sys.stdin.fileno(), 1024)
                channel.send(data)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)
        signal.signal(signal.SIGWINCH, old_handler)
        channel.close()
        ssh_client.close()


@click.command()
@click.argument("execution-id", type=int, required=False)
@opts.cpu_opt
@opts.memory_opt
@opts.image_opt
@opts.region_filter_opt
def shell(execution_id: int | None, cpu, memory, image, region_filter):
    if execution_id is not None:
        data = client.get(f"/executions/{execution_id}/ssh").json()

        interactive_shell(data["host"], data["token"])
    else:
        container_settings = remove_none_values(
            {"cpu": cpu, "memory": memory, "image": image}
        )

        res = client.post(
            "/ssh_sessions",
            json={
                "regions": list(region_filter),
                "container_settings": container_settings,
            },
        )
        id = res.json()["id"]

        with Progress(transient=True) as progress:
            progress.add_task("Waiting for host", total=None)

            while True:
                try:
                    res = client.get(f"/ssh_sessions/{id}")
                    session_data = res.json()
                    break
                except Exception:
                    time.sleep(2)

        interactive_shell(session_data["host"], session_data["token"])
