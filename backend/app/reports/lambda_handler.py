"""Lambda handler for the Builder function (runs inside VPC).

Reads report requests from SQS or direct invocation, generates the CSV
report querying Aurora PostgreSQL, and writes the output directly to S3
via the S3 Gateway VPC Endpoint.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta

import boto3

from app.config import settings
from app.reports.weekly import build_weekly_report


class JsonFormatter(logging.Formatter):
    """Formats log records as structured JSON including extra attributes."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key not in (
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "id",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            ):
                log_obj[key] = value
        return json.dumps(log_obj)


log = logging.getLogger("reports.builder")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(JsonFormatter())
    log.addHandler(_handler)
log.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
log.propagate = False


def detect_trigger(event: dict) -> str:
    """Identify the trigger source from SQS records or direct invocation payload."""
    if "Records" in event and event["Records"]:
        record = event["Records"][0]
        if record.get("eventSource") == "aws:sqs":
            try:
                body = json.loads(record.get("body", "{}"))
                if isinstance(body, dict) and body.get("source"):
                    return str(body["source"])
            except Exception:
                pass
            return "sqs"
        return record.get("eventSource", "sqs")

    if isinstance(event, dict) and event.get("source"):
        return str(event["source"])

    return "direct"


def resolve_week(raw_week: str | None) -> str:
    """Resolve week string; if missing/empty, default to the previous ISO week."""
    if raw_week and raw_week.strip() and raw_week.strip().lower() != "null":
        return raw_week.strip()

    today = datetime.now(settings.tz).date()
    this_monday = today - timedelta(days=today.weekday())
    prev_monday = this_monday - timedelta(days=7)
    iso = prev_monday.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def get_s3_client():
    return boto3.client("s3")


def handler(event, context):
    """Builder Lambda handler entry point."""
    for key in ("DATABASE_URL", "REPORTS_BUCKET", "REPORTS_BUCKET_NAME"):
        if os.environ.get(key):
            os.environ[key] = os.environ[key].strip()

    # 1. Parse payload to extract week
    raw_week = None
    if isinstance(event, dict):
        if "Records" in event and event["Records"]:
            record = event["Records"][0]
            try:
                body = json.loads(record.get("body", "{}"))
                if isinstance(body, dict):
                    raw_week = body.get("week")
            except Exception as e:
                log.warning("Failed to parse SQS message body as JSON: %s", e)
        else:
            raw_week = event.get("week")

    week = resolve_week(raw_week)
    trigger = detect_trigger(event)

    # 2. Structured JSON logging requirement
    log.info("report-builder triggered", extra={"trigger": trigger, "week": week})

    # 3. Generate report CSV bytes
    csv_bytes = build_weekly_report(week)

    # 4. Upload to S3
    raw_bucket = os.environ.get("REPORTS_BUCKET") or os.environ.get("REPORTS_BUCKET_NAME")
    bucket = raw_bucket.strip() if raw_bucket else None
    if not bucket:
        raise ValueError("Missing required REPORTS_BUCKET environment variable")

    key = f"reports/{week}.csv"
    s3 = get_s3_client()
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_bytes,
        ContentType="text/csv",
    )

    log.info(
        "report-builder completed",
        extra={"bucket": bucket, "key": key, "bytes": len(csv_bytes)},
    )

    return {
        "statusCode": 200,
        "bucket": bucket,
        "key": key,
        "week": week,
        "bytes": len(csv_bytes),
    }
