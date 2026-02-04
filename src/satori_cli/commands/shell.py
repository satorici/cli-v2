import fcntl
import os
import select
import signal
import struct
import sys
import termios
import tty

import paramiko
import rich_click as click

from ..api import client


def get_terminal_size():
    buf = fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, b"\x00" * 8)
    rows, cols = struct.unpack("hh", buf[:4])
    return cols, rows


def interactive_shell(ssh_client: paramiko.SSHClient):
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


execution_id_arg = click.argument("execution-id", type=int)


@click.command()
@execution_id_arg
def shell(execution_id: int):
    data = client.get(f"/executions/{execution_id}/ssh").json()

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy)
    ssh_client.connect(hostname=data["host"], username="root", password=data["token"])

    interactive_shell(ssh_client)
