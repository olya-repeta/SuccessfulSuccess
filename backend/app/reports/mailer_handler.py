"""Lambda handler for the Mailer function (runs OUTSIDE VPC in public subnet / standard Lambda).

Triggered by S3 s3:ObjectCreated:* events on reports/*.csv.
Reads the generated CSV from S3, constructs an email attachment,
and dispatches it via Amazon SES sesv2:send_email.

SAFETY RULE:
This function NEVER writes any files back into S3 (especially the reports/ prefix)
to completely eliminate the risk of infinite recursive event loops.
"""

import json
import logging
import os
import sys
import urllib.parse
from email.message import EmailMessage

import boto3

logger = logging.getLogger("reports.mailer")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)


def get_s3_client():
    return boto3.client("s3")


def get_ses_client():
    return boto3.client("sesv2")


def handler(event, context):
    """Mailer Lambda entry point triggered by S3 ObjectCreated events."""
    logger.info("report-mailer triggered: %s", json.dumps(event))

    if not isinstance(event, dict) or "Records" not in event or not event["Records"]:
        logger.warning("No records found in event payload")
        return {"status": "no_records"}

    record = event["Records"][0]
    s3_data = record.get("s3", {})
    bucket = s3_data.get("bucket", {}).get("name")
    raw_key = s3_data.get("object", {}).get("key")

    if not bucket or not raw_key:
        logger.warning("Missing bucket or object key in S3 event record")
        return {"status": "missing_s3_details"}

    key = urllib.parse.unquote_plus(raw_key)

    # Validate key prefix and suffix
    if not key.startswith("reports/") or not key.endswith(".csv"):
        logger.info("Ignoring event for non-report key: %s", key)
        return {"status": "ignored", "key": key}

    filename = os.path.basename(key)
    week = filename[:-4] if filename.endswith(".csv") else filename

    logger.info("Fetching report from s3://%s/%s", bucket, key)
    s3 = get_s3_client()
    response = s3.get_object(Bucket=bucket, Key=key)
    csv_bytes = response["Body"].read()

    sender = os.environ.get("REPORT_SENDER_EMAIL", "reports@example.com").strip()
    recipient_env = os.environ.get("REPORT_RECIPIENT_EMAIL", sender).strip()
    recipients = [r.strip() for r in recipient_env.split(",") if r.strip()]

    # Construct raw email with attachment
    msg = EmailMessage()
    msg["Subject"] = f"Weekly Meetings Report - {week}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(
        f"Hello,\n\n"
        f"Please find attached the Weekly Meetings Report for {week}.\n\n"
        f"Best regards,\n"
        f"SuccessfulSuccess Meetings System"
    )
    msg.add_attachment(
        csv_bytes,
        maintype="text",
        subtype="csv",
        filename=filename,
    )

    logger.info("Dispatching email via SESv2 to %s (sender: %s)", recipients, sender)
    ses = get_ses_client()
    send_response = ses.send_email(
        FromEmailAddress=sender,
        Destination={
            "ToAddresses": recipients,
        },
        Content={
            "Raw": {
                "Data": bytes(msg),
            }
        },
    )

    message_id = send_response.get("MessageId")
    logger.info("Email successfully sent via SESv2 (MessageId: %s)", message_id)

    return {
        "statusCode": 200,
        "messageId": message_id,
        "recipients": recipients,
        "key": key,
    }
