import hashlib
import multiprocessing as mp
import os
import socket
import struct
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import rich_click as click
from netaddr import IPNetwork
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from ..utils.console import stderr, stdout


def is_ip_address(value: str) -> bool:
    """Check if string is an IP address"""
    try:
        socket.inet_aton(value)
        return True
    except socket.error:
        return False


def is_valid_cidr(cidr_str: str) -> bool:
    """Check if string is a valid CIDR notation"""
    try:
        IPNetwork(cidr_str)
        return True
    except Exception:
        return False


def is_valid_ip_range(range_str: str) -> bool:
    """Check if string is a valid IP range (e.g., 192.168.1.1-192.168.1.255)"""
    if "-" not in range_str:
        return False
    try:
        start_ip, end_ip = range_str.split("-", 1)
        return is_ip_address(start_ip.strip()) and is_ip_address(end_ip.strip())
    except Exception:
        return False


def is_direct_input(input_str: str) -> bool:
    """Check if input is a direct IP/CIDR/range instead of a file path"""
    if "/" in input_str and is_valid_cidr(input_str):
        return True
    if "-" in input_str and is_valid_ip_range(input_str):
        return True
    if is_ip_address(input_str):
        return True
    if not os.path.exists(input_str) and ("." in input_str or ":" in input_str):
        return True
    return False


def ip_to_int(ip_str: str) -> int | None:
    """Convert IP string to integer using fast socket.inet_aton"""
    try:
        return struct.unpack("!I", socket.inet_aton(ip_str))[0]
    except socket.error:
        return None


def int_to_ip_str(ip_int: int) -> str:
    """Convert integer to IP string"""
    return socket.inet_ntoa(struct.pack("!I", ip_int))


def hash_string(text: str, seed: int) -> int:
    """Hash any string (domain/URL) for shard selection"""
    hash_input = f"{text}:{seed}".encode("utf-8")
    hash_bytes = hashlib.sha256(hash_input).digest()
    return struct.unpack("!I", hash_bytes[:4])[0] & 0x7FFFFFFF


def extract_domain_from_entry(entry: str) -> str:
    """Extract domain/URL from entry, removing common prefixes and ports"""
    for prefix in ["http://", "https://", "ftp://", "//"]:
        if entry.startswith(prefix):
            entry = entry[len(prefix):]
            break

    if ":" in entry and is_ip_address(entry.split(":")[0]):
        return entry.split(":")[0]

    return entry


def build_blacklist_ranges(file_path: str) -> list:
    """Build sorted list of (start, end) integer ranges for faster lookup"""
    ranges = []

    def parse_entry(entry: str):
        entry = entry.strip()
        if ":" in entry and "/" not in entry and "-" not in entry:
            parts = entry.split(":")
            if is_ip_address(parts[0]):
                entry = parts[0]

        if "/" in entry and (is_ip_address(entry.split("/")[0]) or "." in entry.split("/")[0]):
            network = IPNetwork(entry)
            ranges.append((int(network.first), int(network.last)))
        elif "-" in entry:
            start_ip, end_ip = entry.split("-")
            start_int = ip_to_int(start_ip.strip())
            end_int = ip_to_int(end_ip.strip())
            if start_int and end_int:
                ranges.append((start_int, end_int))
        elif is_ip_address(entry):
            ip_int = ip_to_int(entry)
            if ip_int:
                ranges.append((ip_int, ip_int))

    if is_direct_input(file_path):
        try:
            parse_entry(file_path)
        except Exception:
            pass
    else:
        with open(file_path, "r") as f:
            for line in f:
                entry = line.strip()
                if not entry or entry.startswith("#"):
                    continue
                try:
                    parse_entry(entry)
                except Exception:
                    continue

    ranges.sort()

    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    return merged


def hash_ip_int_vectorized(ip_array: np.ndarray, seed: int) -> np.ndarray:
    """Vectorized hash computation using numpy - MASSIVE speedup"""
    hash_vals = np.full(ip_array.shape, 2166136261, dtype=np.uint64)
    for shift in [0, 8, 16, 24]:
        byte_vals = (ip_array >> shift) & 0xFF
        hash_vals ^= byte_vals
        hash_vals *= 16777619
        hash_vals = hash_vals.astype(np.uint64)

    hash_vals ^= seed
    hash_vals *= 16777619

    return (hash_vals & 0x7FFFFFFF).astype(np.uint32)


def hash_ip_int(ip_int: int, seed: int) -> int:
    """Fast hash using integer directly - fallback for single IPs"""
    hash_val = 2166136261
    hash_val ^= ip_int & 0xFF
    hash_val *= 16777619
    hash_val ^= (ip_int >> 8) & 0xFF
    hash_val *= 16777619
    hash_val ^= (ip_int >> 16) & 0xFF
    hash_val *= 16777619
    hash_val ^= (ip_int >> 24) & 0xFF
    hash_val *= 16777619
    hash_val ^= seed
    hash_val *= 16777619
    return hash_val & 0x7FFFFFFF


def subtract_blacklist_from_range(range_start: int, range_end: int, blacklist_ranges: list) -> list:
    """Pre-filter exclude list to get only valid IP segments"""
    if not blacklist_ranges:
        return [(range_start, range_end)]

    valid_segments = []
    current_start = range_start

    for bl_start, bl_end in blacklist_ranges:
        if bl_end < range_start or bl_start > range_end:
            continue

        if current_start < bl_start:
            valid_segments.append((current_start, min(bl_start - 1, range_end)))

        current_start = max(current_start, bl_end + 1)

        if current_start > range_end:
            break

    if current_start <= range_end:
        valid_segments.append((current_start, range_end))

    return valid_segments


def process_ip_range_pre_filtered(
    range_start: int, range_end: int, blacklist_ranges: list, shard_x: int, shard_y: int, seed: int
) -> tuple:
    """Process only non-excluded segments - skip billions of excluded IPs"""

    valid_segments = subtract_blacklist_from_range(range_start, range_end, blacklist_ranges)

    if not valid_segments:
        total_processed = range_end - range_start + 1
        return total_processed, total_processed, []

    total_processed = range_end - range_start + 1
    total_excluded = total_processed - sum(seg_end - seg_start + 1 for seg_start, seg_end in valid_segments)
    selected_ips = []

    for seg_start, seg_end in valid_segments:
        seg_size = seg_end - seg_start + 1

        if seg_size > 100000:
            chunk_size = 1000000

            for chunk_start in range(seg_start, seg_end + 1, chunk_size):
                chunk_end = min(chunk_start + chunk_size - 1, seg_end)

                ip_array = np.arange(chunk_start, chunk_end + 1, dtype=np.uint32)

                hash_values = hash_ip_int_vectorized(ip_array, seed)

                shard_mask = (hash_values % shard_y) == (shard_x - 1)
                selected_ip_ints = ip_array[shard_mask]

                for ip_int in selected_ip_ints:
                    selected_ips.append(int_to_ip_str(int(ip_int)))
        else:
            for ip_int in range(seg_start, seg_end + 1):
                hash_val = hash_ip_int(ip_int, seed)
                if (hash_val % shard_y) == (shard_x - 1):
                    selected_ips.append(int_to_ip_str(ip_int))

    return total_processed, total_excluded, selected_ips


def parse_direct_input(input_str: str) -> tuple:
    """Parse direct input and return (ip_ranges, non_ip_entries)"""
    ip_ranges = []
    non_ip_entries = []

    entry = input_str.strip()
    try:
        if ":" in entry and "/" not in entry and "-" not in entry:
            parts = entry.split(":")
            if is_ip_address(parts[0]):
                entry = parts[0]

        if "/" in entry and (
            is_ip_address(entry.split("/")[0]) or (entry.count(".") >= 3 and "-" not in entry)
        ):
            network = IPNetwork(entry)
            ip_ranges.append((int(network.first), int(network.last)))
        elif "-" in entry and is_ip_address(entry.split("-")[0].strip()):
            start_ip, end_ip = entry.split("-")
            start_int = ip_to_int(start_ip.strip())
            end_int = ip_to_int(end_ip.strip())
            if start_int and end_int:
                ip_ranges.append((start_int, end_int))
        elif is_ip_address(entry):
            ip_int = ip_to_int(entry)
            if ip_int:
                ip_ranges.append((ip_int, ip_int))
        else:
            clean_entry = extract_domain_from_entry(entry)
            if clean_entry:
                non_ip_entries.append(clean_entry)
    except Exception:
        clean_entry = extract_domain_from_entry(entry)
        if clean_entry:
            non_ip_entries.append(clean_entry)

    return ip_ranges, non_ip_entries


def read_file_addresses_ultra_parallel(
    file_path: str, blacklist_ranges: list, shard_x: int, shard_y: int, seed: int
) -> tuple:
    """Ultra parallel processing with dynamic work queue for perfect load balancing"""

    num_processes = mp.cpu_count()

    ip_ranges = []
    non_ip_entries = []

    if is_direct_input(file_path):
        ip_ranges, non_ip_entries = parse_direct_input(file_path)
    else:
        with open(file_path, "r") as f:
            for line in f:
                entry = line.strip()
                if not entry or entry.startswith("#"):
                    continue
                try:
                    if ":" in entry and "/" not in entry and "-" not in entry:
                        parts = entry.split(":")
                        if is_ip_address(parts[0]):
                            entry = parts[0]

                    if "/" in entry and (
                        is_ip_address(entry.split("/")[0])
                        or (entry.count(".") >= 3 and "-" not in entry)
                    ):
                        network = IPNetwork(entry)
                        ip_ranges.append((int(network.first), int(network.last)))
                    elif "-" in entry and is_ip_address(entry.split("-")[0].strip()):
                        start_ip, end_ip = entry.split("-")
                        start_int = ip_to_int(start_ip.strip())
                        end_int = ip_to_int(end_ip.strip())
                        if start_int and end_int:
                            ip_ranges.append((start_int, end_int))
                    elif is_ip_address(entry):
                        ip_int = ip_to_int(entry)
                        if ip_int:
                            ip_ranges.append((ip_int, ip_int))
                    else:
                        clean_entry = extract_domain_from_entry(entry)
                        if clean_entry:
                            non_ip_entries.append(clean_entry)
                except Exception:
                    clean_entry = extract_domain_from_entry(entry)
                    if clean_entry:
                        non_ip_entries.append(clean_entry)

    selected_non_ip = []
    for entry in non_ip_entries:
        hash_val = hash_string(entry, seed)
        if (hash_val % shard_y) == (shard_x - 1):
            selected_non_ip.append(entry)

    work_chunks = []
    chunk_size = 25_000_000

    for start, end in ip_ranges:
        range_size = end - start + 1

        if range_size > chunk_size:
            current_start = start
            while current_start <= end:
                chunk_end = min(current_start + chunk_size - 1, end)
                work_chunks.append((current_start, chunk_end))
                current_start = chunk_end + 1
        else:
            work_chunks.append((start, end))

    total_processed = len(non_ip_entries)
    total_excluded = 0
    all_selected = selected_non_ip.copy()

    with ProcessPoolExecutor(max_workers=num_processes) as executor:
        future_to_chunk = {}
        for i, chunk in enumerate(work_chunks):
            future = executor.submit(
                _process_prefiltered_chunk_worker, chunk, blacklist_ranges, shard_x, shard_y, seed, i
            )
            future_to_chunk[future] = i

        for future in as_completed(future_to_chunk):
            chunk_id = future_to_chunk[future]
            try:
                chunk_processed, chunk_excluded, chunk_selected = future.result()
                total_processed += chunk_processed
                total_excluded += chunk_excluded
                all_selected.extend(chunk_selected)
            except Exception as exc:
                stderr.print(f"Error in chunk {chunk_id}: {exc}")

    return total_processed, total_excluded, all_selected


def count_total_items(file_path: str) -> int:
    """Quick count of total items (IPs + domains/URLs) for progress tracking"""
    total = 0

    def count_entry(entry: str) -> int:
        entry = entry.strip()
        if ":" in entry and "/" not in entry and "-" not in entry:
            parts = entry.split(":")
            if is_ip_address(parts[0]):
                entry = parts[0]

        if "/" in entry and (
            is_ip_address(entry.split("/")[0]) or (entry.count(".") >= 3 and "-" not in entry)
        ):
            network = IPNetwork(entry)
            return int(network.last) - int(network.first) + 1
        elif "-" in entry and is_ip_address(entry.split("-")[0].strip()):
            start_ip, end_ip = entry.split("-")
            start_int = ip_to_int(start_ip.strip())
            end_int = ip_to_int(end_ip.strip())
            if start_int and end_int:
                return end_int - start_int + 1
            return 1
        else:
            return 1

    if is_direct_input(file_path):
        try:
            total += count_entry(file_path)
        except Exception:
            total += 1
    else:
        with open(file_path, "r") as f:
            for line in f:
                entry = line.strip()
                if not entry or entry.startswith("#"):
                    continue
                try:
                    total += count_entry(entry)
                except Exception:
                    total += 1

    return total


def _process_prefiltered_chunk_worker(
    chunk_range: tuple, blacklist_ranges: list, shard_x: int, shard_y: int, seed: int, chunk_id: int
) -> tuple:
    """Worker with exclude list pre-filtering - skip billions of excluded IPs"""
    range_start, range_end = chunk_range
    return process_ip_range_pre_filtered(range_start, range_end, blacklist_ranges, shard_x, shard_y, seed)


@click.command()
@click.option("--shard", required=True, help="Current shard and total (X/Y format)")
@click.option("--seed", type=int, default=1, show_default=True, help="Seed for pseudorandom permutation")
@click.option(
    "--input",
    "input_file",
    required=True,
    help="Input file with addresses OR direct IP/CIDR (e.g., 192.168.1.0/24, 10.0.0.1-10.0.0.255)",
)
@click.option(
    "--exclude",
    "exclude_file",
    help="File with addresses to exclude OR direct IP/CIDR to exclude (e.g., 192.168.1.0/24)",
)
@click.option(
    "--results",
    "results_file",
    help="Save results to text file (must have .txt extension or no extension; default is .txt)",
)
def shards(shard: str, seed: int, input_file: str, exclude_file: str | None, results_file: str | None):
    """Deterministically split IPs/domains into shards for distributed scanning."""
    try:
        x_str, y_str = shard.split("/")
        shard_x = int(x_str)
        shard_y = int(y_str)
    except ValueError:
        raise click.BadParameter("Invalid format for --shard. Use X/Y", param_hint="'--shard'")

    if shard_y < 1 or shard_x < 1 or shard_x > shard_y:
        raise click.BadParameter(f"Invalid shard value: {shard_x}/{shard_y}", param_hint="'--shard'")

    blacklist_ranges = []
    if exclude_file:
        try:
            blacklist_ranges = build_blacklist_ranges(exclude_file)
        except Exception as e:
            raise click.ClickException(f"Failed to load exclude list: {e}")

    total_items = count_total_items(input_file)

    stderr.print(f"Processing {total_items:,} items")

    start_time = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Running..."),
        TimeElapsedColumn(),
        console=stderr,
        refresh_per_second=10,
    ) as progress:
        progress.add_task("Processing...", total=None)
        total_processed, total_excluded, selected_items = read_file_addresses_ultra_parallel(
            input_file, blacklist_ranges, shard_x, shard_y, seed
        )

    end_time = time.time()

    stderr.print(
        f"Completed in {end_time - start_time:.1f}s - "
        f"Selected {len(selected_items):,} items - Excluded {total_excluded:,} IPs"
    )

    if results_file:
        try:
            output_path = Path(results_file)
            extension = output_path.suffix.lower()
            if not extension:
                output_path = Path(str(output_path) + ".txt")
            elif extension != ".txt":
                raise click.ClickException(
                    f"Unsupported file extension: {extension}. Only .txt format is supported."
                )

            os.makedirs(output_path.parent, exist_ok=True)

            with open(output_path, "w") as f:
                for addr in selected_items:
                    f.write(f"{addr}\n")
            stderr.print(f"Saved to {output_path}")
        except click.ClickException:
            raise
        except Exception as e:
            raise click.ClickException(f"Failed to write output file: {e}")
    else:
        for addr in selected_items:
            stdout.print(addr, highlight=False, markup=False, soft_wrap=True)
