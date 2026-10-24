"""Generate owner-scoped document renewal notifications idempotently."""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_INTERVALS = (30, 7, 0)
DATE_FORMAT = "%Y-%m-%d"


def application_today(timezone_name, now=None):
    zone = ZoneInfo(timezone_name)
    current = now or datetime.now(zone)
    return current.astimezone(zone).date()


def parse_date(value, field_name):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must use YYYY-MM-DD.") from error


def normalize_intervals(value):
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("Reminder intervals must be a JSON list.") from error
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) or item not in DEFAULT_INTERVALS
        for item in value
    ):
        raise ValueError("Reminder intervals must contain only 30, 7, or 0.")
    return sorted(set(value), reverse=True)


def validate_metadata(document_name, issue_date, expiry_date, reminder_intervals):
    if document_name is not None and (not isinstance(document_name, str) or len(document_name.strip()) > 255):
        raise ValueError("Document name must be 255 characters or fewer.")
    parsed_issue = parse_date(issue_date, "Issue date")
    parsed_expiry = parse_date(expiry_date, "Expiry date")
    if parsed_issue and parsed_expiry and parsed_issue > parsed_expiry:
        raise ValueError("Issue date cannot be after the expiry date.")
    intervals = normalize_intervals(reminder_intervals)
    if parsed_expiry is None and intervals:
        raise ValueError("Reminder intervals require an expiry date.")
    return (
        document_name.strip() if isinstance(document_name, str) and document_name.strip() else None,
        parsed_issue.isoformat() if parsed_issue else None,
        parsed_expiry.isoformat() if parsed_expiry else None,
        intervals,
    )


def generate_notifications(connection, today=None, timezone_name="Asia/Kolkata"):
    """Create due notifications for all configured documents; returns inserted count."""
    current_day = today or application_today(timezone_name)
    rows = connection.execute(
        """
        SELECT id, user_id, original_filename, display_name, expiry_date, reminder_intervals
        FROM documents
        WHERE expiry_date IS NOT NULL AND reminder_intervals IS NOT NULL
        """
    ).fetchall()
    inserted = 0
    for row in rows:
        intervals = normalize_intervals(row["reminder_intervals"])
        expiry = parse_date(row["expiry_date"], "Expiry date")
        for interval in intervals:
            reminder_day = expiry - timedelta(days=interval)
            if reminder_day > current_day:
                continue
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO notifications (
                    user_id, document_id, kind, due_date, reminder_interval,
                    message_key, created_at
                ) VALUES (?, ?, 'document_renewal', ?, ?, 'documentRenewal', ?)
                """,
                (
                    row["user_id"],
                    row["id"],
                    expiry.isoformat(),
                    interval,
                    datetime.now(ZoneInfo(timezone_name)).isoformat(),
                ),
            )
            inserted += cursor.rowcount
    return inserted


def list_notifications(connection, user_id, today):
    return connection.execute(
        """
        SELECT n.id, n.document_id, n.due_date, n.reminder_interval, n.status,
               COALESCE(d.display_name, d.original_filename) AS document_name
        FROM notifications n
        JOIN documents d ON d.id = n.document_id AND d.user_id = n.user_id
        WHERE n.user_id = ? AND n.status = 'unread'
        ORDER BY n.due_date ASC, n.reminder_interval DESC, n.id ASC
        """,
        (user_id,),
    ).fetchall()


def notification_state(due_date, today):
    due = date.fromisoformat(due_date)
    if due < today:
        return "overdue"
    if due == today:
        return "due_today"
    return "upcoming"


def run_scheduled_job(database_path, timezone_name="Asia/Kolkata", now=None):
    """Entry point for cron/systemd; no email or external delivery is performed."""
    from database.db import get_connection

    with get_connection(database_path) as connection:
        return generate_notifications(
            connection,
            today=application_today(timezone_name, now),
            timezone_name=timezone_name,
        )


if __name__ == "__main__":
    import argparse
    from config import Config

    parser = argparse.ArgumentParser(description="Generate LifeGraph document reminders.")
    parser.add_argument("--database", default=Config.DATABASE_PATH)
    parser.add_argument("--timezone", default=Config.TIMEZONE)
    args = parser.parse_args()
    print(run_scheduled_job(args.database, args.timezone))
