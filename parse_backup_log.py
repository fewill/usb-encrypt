"""
parse_backup_log.py — Parse a backup log file and print a Slack-ready summary.

Usage:
    python3 parse_backup_log.py /path/to/backup-YYYY-MM-DD_HH-MM-SS.log
"""

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S"


def parse_log(path: Path) -> dict:
    text = path.read_text(errors="replace")
    lines = text.splitlines()

    result = {}

    # Start / end timestamps
    m = re.search(r"Starting backup — (.+)", text)
    if m:
        result["start"] = datetime.strptime(m.group(1).strip(), TIMESTAMP_FMT)

    m = re.search(r"Backup complete — (.+)", text)
    if m:
        result["ssd_end"] = datetime.strptime(m.group(1).strip(), TIMESTAMP_FMT)

    # Directories synced (absolute paths only — excludes "Syncing to S3...")
    result["dirs"] = re.findall(r"^Syncing (/\S+)\.\.\.", text, re.MULTILINE)

    # rclone: size transferred — e.g. "562.869 MiB / 562.869 MiB, 100%, 107 KiB/s"
    size_matches = re.findall(
        r"Transferred:\s+([\d.]+\s+\w+)\s*/\s*([\d.]+\s+\w+),\s*100%", text
    )
    if size_matches:
        result["s3_transferred_size"] = size_matches[-1][0]

    # rclone: files transferred — e.g. "Transferred:         1389 / 1389, 100%"
    count_matches = re.findall(
        r"Transferred:\s+(\d[\d,]*)\s*/\s*(\d[\d,]*),\s*100%\s*$", text, re.MULTILINE
    )
    if count_matches:
        result["s3_files_transferred"] = int(count_matches[-1][0].replace(",", ""))

    # rclone: checks
    check_matches = re.findall(
        r"Checks:\s+([\d,]+)\s*/\s*([\d,]+),\s*100%", text
    )
    if check_matches:
        result["s3_files_checked"] = int(check_matches[-1][0].replace(",", ""))

    # rclone: deleted
    del_matches = re.findall(
        r"Deleted:\s+([\d,]+)\s+\(files\),\s*([\d,]+)\s+\(dirs\)", text
    )
    if del_matches:
        result["s3_deleted_files"] = int(del_matches[-1][0].replace(",", ""))
        result["s3_deleted_dirs"] = int(del_matches[-1][1].replace(",", ""))

    # rclone: errors
    err_matches = re.findall(r"^Errors:\s+(\d+)", text, re.MULTILINE)
    result["s3_errors"] = int(err_matches[-1]) if err_matches else 0

    # rclone: elapsed time (last occurrence = final summary)
    elapsed_matches = re.findall(r"Elapsed time:\s+(.+)", text)
    if elapsed_matches:
        result["s3_elapsed"] = elapsed_matches[-1].strip()

    # Total elapsed (start to S3 complete)
    s3_end_matches = re.findall(r"S3 sync complete", text)
    if s3_end_matches and "start" in result:
        # Use log file mtime as proxy for S3 completion time if we can't parse it
        # Instead, derive from s3_elapsed string
        pass  # handled in build_summary via s3_elapsed

    return result


def get_ssd_free(mount_point: str) -> str | None:
    try:
        usage = shutil.disk_usage(mount_point)
        free_gb = usage.free / (1024 ** 3)
        if free_gb >= 1000:
            return f"{free_gb / 1024:.1f} TiB free"
        return f"{free_gb:.0f} GiB free"
    except OSError:
        return None


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def fmt_count(n: int) -> str:
    return f"{n:,}"


def build_summary(data: dict, mount_point: str | None = None) -> str:
    lines = []

    # SSD section
    if "start" in data and "ssd_end" in data:
        ssd_secs = (data["ssd_end"] - data["start"]).total_seconds()
        dir_count = len(data.get("dirs", []))
        ssd_line = f"• SSD: {dir_count} dirs synced in {fmt_duration(ssd_secs)}"
        if mount_point:
            free = get_ssd_free(mount_point)
            if free:
                ssd_line += f" — {free}"
        lines.append(ssd_line)

    # S3 section
    s3_parts = []
    if "s3_transferred_size" in data:
        s3_parts.append(f"{data['s3_transferred_size']} transferred")
    if "s3_files_transferred" in data:
        s3_parts.append(f"{fmt_count(data['s3_files_transferred'])} files uploaded")
    if "s3_files_checked" in data:
        s3_parts.append(f"{fmt_count(data['s3_files_checked'])} checked")
    if "s3_deleted_files" in data:
        deleted = data["s3_deleted_files"]
        if deleted > 0:
            s3_parts.append(f"{fmt_count(deleted)} deleted")

    errors = data.get("s3_errors", 0)
    if errors:
        s3_parts.append(f"*{errors} errors*")

    if s3_parts:
        lines.append(f"• S3: {', '.join(s3_parts)}")

    # Total elapsed
    if "s3_elapsed" in data:
        lines.append(f"• Total time: {data['s3_elapsed']}")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <log_file> [mount_point]", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Log file not found: {path}", file=sys.stderr)
        sys.exit(1)

    mount_point = sys.argv[2] if len(sys.argv) >= 3 else None
    data = parse_log(path)
    print(build_summary(data, mount_point))


if __name__ == "__main__":
    main()
