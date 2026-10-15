"""Tests for weekly report generation, builder Lambda handler, and mailer Lambda handler."""

import io
import json
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.meeting import Meeting, Participant
from app.reports.lambda_handler import (
    detect_trigger,
    resolve_week,
)
from app.reports.lambda_handler import (
    handler as builder_handler,
)
from app.reports.mailer_handler import handler as mailer_handler
from app.reports.weekly import (
    build_weekly_report_async,
    get_prior_iso_week,
    parse_iso_week,
)


def test_parse_iso_week_valid():
    assert parse_iso_week("2026-W40") == (2026, 40)
    assert parse_iso_week("2025-W01") == (2025, 1)
    assert parse_iso_week("2020-W53") == (2020, 53)


def test_parse_iso_week_invalid():
    with pytest.raises(ValueError, match="Invalid ISO week format"):
        parse_iso_week("2026-40")
    with pytest.raises(ValueError, match="Invalid ISO week format"):
        parse_iso_week("invalid")
    with pytest.raises(ValueError, match="Invalid ISO week number"):
        parse_iso_week("2026-W00")
    with pytest.raises(ValueError, match="Invalid ISO week number"):
        parse_iso_week("2026-W54")


def test_get_prior_iso_week():
    prior_str, prior_mon = get_prior_iso_week(2026, 40)
    assert prior_str == "2026-W39"
    assert prior_mon == date(2026, 9, 21)

    prior_str_jan, prior_mon_jan = get_prior_iso_week(2026, 1)
    assert prior_str_jan == "2025-W52"
    assert prior_mon_jan == date(2025, 12, 22)


async def test_build_weekly_report_calculations(session: AsyncSession):
    # Week 2026-W40: Monday 2026-09-28 to Sunday 2026-10-04
    # Prior Week 2026-W39: Monday 2026-09-21 to Sunday 2026-09-27
    tz = settings.tz
    mon_w40 = datetime.combine(date(2026, 9, 28), time(10, 0), tzinfo=tz)
    tue_w40 = datetime.combine(date(2026, 9, 29), time(14, 0), tzinfo=tz)
    wed_w40 = datetime.combine(date(2026, 9, 30), time(9, 0), tzinfo=tz)
    mon_w39 = datetime.combine(date(2026, 9, 21), time(11, 0), tzinfo=tz)

    # Prior week meeting: 1 meeting, 1 hour
    prior_meeting = Meeting(
        name="Sprint Review W39",
        starts_at=mon_w39,
        ends_at=mon_w39 + timedelta(hours=1),
        participants=[Participant(name="Alice", position=0)],
    )
    session.add(prior_meeting)

    # Current week meetings:
    # 1. 3 hours, 2 participants
    # 2. 1.5 hours, 3 participants
    # 3. 0.5 hours, 0 participants
    m1 = Meeting(
        name="Strategy Session",
        starts_at=mon_w40,
        ends_at=mon_w40 + timedelta(hours=3),
        participants=[
            Participant(name="Alice", position=0),
            Participant(name="Bob", position=1),
        ],
    )
    m2 = Meeting(
        name="Quarterly Sync",
        starts_at=tue_w40,
        ends_at=tue_w40 + timedelta(hours=1, minutes=30),
        participants=[
            Participant(name="Charlie", position=0),
            Participant(name="Dave", position=1),
            Participant(name="Eve", position=2),
        ],
    )
    m3 = Meeting(
        name="Quick Standup",
        starts_at=wed_w40,
        ends_at=wed_w40 + timedelta(minutes=30),
        participants=[],
    )
    session.add_all([m1, m2, m3])
    await session.commit()

    csv_bytes = await build_weekly_report_async("2026-W40", session=session)
    content = csv_bytes.decode("utf-8")
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]

    # Metric,Current Week (2026-W40),Prior Week (2026-W39),Delta
    assert "Metric,Current Week (2026-W40),Prior Week (2026-W39),Delta" in lines[0]
    # Meeting Count: current 3, prior 1, delta +2
    assert "Meeting Count,3,1,+2" in lines[1]
    # Total Duration: current 5.00, prior 1.00, delta +4.00
    assert "Total Duration (hours),5.00,1.00,+4.00" in lines[2]

    # Top meetings: Strategy Session (3.00), Quarterly Sync (1.50), Quick Standup (0.50)
    assert "Title,Start Time,Duration (hours),Participant Count" in lines[3]
    assert lines[4].startswith("Strategy Session,")
    assert ",3.00,2" in lines[4]
    assert lines[5].startswith("Quarterly Sync,")
    assert ",1.50,3" in lines[5]
    assert lines[6].startswith("Quick Standup,")
    assert ",0.50,0" in lines[6]


async def test_top_5_limit(session: AsyncSession):
    tz = settings.tz
    mon = datetime.combine(date(2026, 9, 28), time(8, 0), tzinfo=tz)

    meetings = []
    for i in range(7):
        meetings.append(
            Meeting(
                name=f"Meeting {i}",
                starts_at=mon + timedelta(hours=i * 2),
                ends_at=mon + timedelta(hours=i * 2 + 1),  # 1 hour each
                participants=[],
            )
        )
    session.add_all(meetings)
    await session.commit()

    csv_bytes = await build_weekly_report_async("2026-W40", session=session)
    content = csv_bytes.decode("utf-8")
    header = "Title,Start Time,Duration (hours),Participant Count"
    table_lines = [line for line in content.split(header)[1].strip().splitlines() if line.strip()]
    assert len(table_lines) == 5


def test_detect_trigger():
    assert detect_trigger({"source": "manual"}) == "manual"
    assert detect_trigger({"source": "direct"}) == "direct"
    assert detect_trigger({}) == "direct"

    sqs_event_scheduled = {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "body": json.dumps({"week": None, "source": "schedule"}),
            }
        ]
    }
    assert detect_trigger(sqs_event_scheduled) == "schedule"

    sqs_event_manual = {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "body": json.dumps({"week": "2026-W40", "source": "manual"}),
            }
        ]
    }
    assert detect_trigger(sqs_event_manual) == "manual"


def test_resolve_week():
    assert resolve_week("2026-W40") == "2026-W40"
    assert resolve_week("  2026-W42  ") == "2026-W42"

    # Default to previous week when null/empty
    default_week = resolve_week(None)
    assert "-W" in default_week
    assert resolve_week("") == default_week
    assert resolve_week("null") == default_week


@patch("app.reports.lambda_handler.build_weekly_report")
@patch("app.reports.lambda_handler.get_s3_client")
def test_builder_handler(mock_get_s3, mock_build_report, monkeypatch):
    monkeypatch.setenv("REPORTS_BUCKET", "test-bucket")
    mock_s3 = MagicMock()
    mock_get_s3.return_value = mock_s3
    mock_build_report.return_value = b"sample,csv,data\n"

    # Direct invocation
    event = {"week": "2026-W40", "source": "direct"}
    res = builder_handler(event, None)

    assert res["statusCode"] == 200
    assert res["week"] == "2026-W40"
    assert res["key"] == "reports/2026-W40.csv"
    assert res["bucket"] == "test-bucket"

    mock_s3.put_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="reports/2026-W40.csv",
        Body=b"sample,csv,data\n",
        ContentType="text/csv",
    )


@patch("app.reports.lambda_handler.build_weekly_report")
@patch("app.reports.lambda_handler.get_s3_client")
def test_builder_handler_from_sqs(mock_get_s3, mock_build_report, monkeypatch):
    monkeypatch.setenv("REPORTS_BUCKET", "test-bucket")
    mock_s3 = MagicMock()
    mock_get_s3.return_value = mock_s3
    mock_build_report.return_value = b"sample,csv,data\n"

    event = {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "body": json.dumps({"week": "2026-W41", "source": "manual"}),
            }
        ]
    }
    res = builder_handler(event, None)

    assert res["statusCode"] == 200
    assert res["week"] == "2026-W41"
    assert res["key"] == "reports/2026-W41.csv"


@patch("app.reports.mailer_handler.get_ses_client")
@patch("app.reports.mailer_handler.get_s3_client")
def test_mailer_handler_success(mock_get_s3, mock_get_ses, monkeypatch):
    monkeypatch.setenv("REPORT_SENDER_EMAIL", "sender@example.com")
    monkeypatch.setenv("REPORT_RECIPIENT_EMAIL", "recipient@example.com")

    mock_s3 = MagicMock()
    mock_get_s3.return_value = mock_s3
    mock_s3.get_object.return_value = {"Body": io.BytesIO(b"Metric,Current\nMeeting Count,5\n")}

    mock_ses = MagicMock()
    mock_get_ses.return_value = mock_ses
    mock_ses.send_email.return_value = {"MessageId": "msg-12345"}

    s3_event = {
        "Records": [
            {
                "eventSource": "aws:s3",
                "s3": {
                    "bucket": {"name": "my-reports-bucket"},
                    "object": {"key": "reports/2026-W40.csv"},
                },
            }
        ]
    }

    res = mailer_handler(s3_event, None)

    assert res["statusCode"] == 200
    assert res["messageId"] == "msg-12345"
    assert res["key"] == "reports/2026-W40.csv"
    assert res["recipients"] == ["recipient@example.com"]

    mock_s3.get_object.assert_called_once_with(
        Bucket="my-reports-bucket",
        Key="reports/2026-W40.csv",
    )
    # Verify SES was invoked with Raw email
    mock_ses.send_email.assert_called_once()
    call_kwargs = mock_ses.send_email.call_args[1]
    assert call_kwargs["FromEmailAddress"] == "sender@example.com"
    assert call_kwargs["Destination"]["ToAddresses"] == ["recipient@example.com"]
    raw_data = call_kwargs["Content"]["Raw"]["Data"]
    assert b"Subject: Weekly Meetings Report - 2026-W40" in raw_data
    import email

    parsed_email = email.message_from_bytes(raw_data)
    attachments = [part for part in parsed_email.walk() if part.get_filename() == "2026-W40.csv"]
    assert len(attachments) == 1
    assert b"Metric,Current" in attachments[0].get_payload(decode=True)

    # CRITICAL: Verify safety rule - mailer NEVER calls put_object on S3
    assert not hasattr(mock_s3, "put_object") or mock_s3.put_object.call_count == 0


def test_mailer_handler_ignores_non_report_keys():
    s3_event = {
        "Records": [
            {
                "eventSource": "aws:s3",
                "s3": {
                    "bucket": {"name": "my-reports-bucket"},
                    "object": {"key": "other/file.txt"},
                },
            }
        ]
    }
    res = mailer_handler(s3_event, None)
    assert res["status"] == "ignored"
