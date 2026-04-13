"""Tests for parse_backup_log.py"""

import textwrap
from datetime import datetime
from pathlib import Path

import pytest

from parse_backup_log import (
    build_summary,
    fmt_duration,
    fmt_count,
    get_ssd_free,
    parse_log,
)

SAMPLE_LOG = textwrap.dedent("""\

    Starting backup — 2026-04-08 07:24:52
    ----------------------------------------
    Syncing /home/fewill/code...
    Syncing /home/fewill/Documents...
    Syncing /home/fewill/Pictures...
    Syncing /home/fewill/Downloads...
    Syncing /home/fewill/Desktop...
    Syncing /home/fewill/.ssh...
    Syncing /home/fewill/.config...
    Syncing /home/fewill/.local/share...
    Syncing /home/fewill/.mozilla...
    Syncing /home/fewill/.zoom...
    Syncing /etc...
    ----------------------------------------
    Backup complete — 2026-04-08 07:25:23
    Syncing to S3...
    Transferred:   	  562.869 MiB / 562.869 MiB, 100%, 107.494 KiB/s, ETA 0s
    Errors:               0
    Checks:            965861 / 965861, 100%
    Transferred:         1389 / 1389, 100%
    Elapsed time:   3h3m11.2s
    Deleted:             1250 (files), 0 (dirs)
    Transferred:   	  562.869 MiB / 562.869 MiB, 100%, 107.494 KiB/s, ETA 0s
    Errors:               0
    Checks:            965861 / 965861, 100%
    Transferred:         1389 / 1389, 100%
    Elapsed time:   3h3m11.2s
    S3 sync complete.
""")

SAMPLE_LOG_WITH_ERRORS = textwrap.dedent("""\

    Starting backup — 2026-04-06 12:41:57
    ----------------------------------------
    Syncing /home/fewill/code...
    Backup complete — 2026-04-06 22:11:00
    Transferred:   	    6.239 GiB / 6.239 GiB, 100%, 40.054 KiB/s, ETA 0s
    Errors:               115 (retrying may help)
    Checks:           2866633 / 2866633, 100%
    Transferred:        28378 / 28378, 100%
    Elapsed time:   9h28m45.2s
""")


@pytest.fixture
def log_file(tmp_path):
    def _make(content):
        p = tmp_path / "backup.log"
        p.write_text(content)
        return p
    return _make


class TestParseLog:
    def test_start_timestamp(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        assert data["start"] == datetime(2026, 4, 8, 7, 24, 52)

    def test_ssd_end_timestamp(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        assert data["ssd_end"] == datetime(2026, 4, 8, 7, 25, 23)

    def test_dirs_synced(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        assert len(data["dirs"]) == 11
        assert "/home/fewill/code" in data["dirs"]
        assert "/etc" in data["dirs"]

    def test_s3_transferred_size(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        assert data["s3_transferred_size"] == "562.869 MiB"

    def test_s3_files_transferred(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        assert data["s3_files_transferred"] == 1389

    def test_s3_files_checked(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        assert data["s3_files_checked"] == 965861

    def test_s3_deleted(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        assert data["s3_deleted_files"] == 1250
        assert data["s3_deleted_dirs"] == 0

    def test_s3_no_errors(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        assert data["s3_errors"] == 0

    def test_s3_errors(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG_WITH_ERRORS))
        assert data["s3_errors"] == 115

    def test_s3_elapsed(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        assert data["s3_elapsed"] == "3h3m11.2s"

    def test_missing_timestamps(self, log_file):
        data = parse_log(log_file("No timestamps here.\n"))
        assert "start" not in data
        assert "ssd_end" not in data


class TestBuildSummary:
    def test_full_summary(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        summary = build_summary(data)
        assert "11 dirs synced" in summary
        assert "31s" in summary
        assert "562.869 MiB" in summary
        assert "1,389 files uploaded" in summary
        assert "965,861 checked" in summary
        assert "1,250 deleted" in summary
        assert "3h3m11.2s" in summary

    def test_errors_highlighted(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG_WITH_ERRORS))
        summary = build_summary(data)
        assert "*115 errors*" in summary

    def test_no_deleted_when_zero(self, log_file):
        log = SAMPLE_LOG.replace("1250 (files), 0 (dirs)", "0 (files), 0 (dirs)")
        data = parse_log(log_file(log))
        summary = build_summary(data)
        assert "deleted" not in summary

    def test_ssd_free_shown_when_mount_provided(self, log_file, tmp_path):
        data = parse_log(log_file(SAMPLE_LOG))
        summary = build_summary(data, mount_point=str(tmp_path))
        assert "free" in summary

    def test_ssd_free_omitted_when_no_mount(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        summary = build_summary(data, mount_point=None)
        assert "free" not in summary

    def test_ssd_free_omitted_when_invalid_mount(self, log_file):
        data = parse_log(log_file(SAMPLE_LOG))
        summary = build_summary(data, mount_point="/nonexistent/path")
        assert "free" not in summary

    def test_empty_log(self, log_file):
        data = parse_log(log_file(""))
        summary = build_summary(data)
        assert summary == ""


class TestFmtDuration:
    def test_seconds_only(self):
        assert fmt_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert fmt_duration(125) == "2m 5s"

    def test_hours_and_minutes(self):
        assert fmt_duration(3600 + 180) == "1h 3m"

    def test_zero(self):
        assert fmt_duration(0) == "0s"


class TestFmtCount:
    def test_thousands(self):
        assert fmt_count(1389) == "1,389"

    def test_millions(self):
        assert fmt_count(965861) == "965,861"

    def test_small(self):
        assert fmt_count(42) == "42"


class TestGetSsdFree:
    def test_returns_string_for_valid_path(self, tmp_path):
        result = get_ssd_free(str(tmp_path))
        assert result is not None
        assert "free" in result

    def test_returns_none_for_invalid_path(self):
        result = get_ssd_free("/nonexistent/mount")
        assert result is None
