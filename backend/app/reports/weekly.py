"""Weekly meetings report generation business logic."""

import asyncio
import concurrent.futures
import csv
import io
import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.meeting import Meeting


def parse_iso_week(week: str) -> tuple[int, int]:
    """Parse and validate an ISO week string in 'YYYY-Www' format."""
    match = re.match(r"^(\d{4})-W(\d{2})$", week.strip())
    if not match:
        raise ValueError(
            f"Invalid ISO week format '{week}'. Expected format 'YYYY-Www' (e.g. '2026-W40')."
        )
    year = int(match.group(1))
    week_num = int(match.group(2))
    if week_num < 1 or week_num > 53:
        raise ValueError(f"Invalid ISO week number {week_num}. Must be between 1 and 53.")
    # Validate against calendar (handles 53-week leap years vs 52-week years)
    try:
        date.fromisocalendar(year, week_num, 1)
    except ValueError as e:
        raise ValueError(f"Invalid ISO calendar week '{week}': {e}") from e
    return year, week_num


def get_prior_iso_week(year: int, week_num: int) -> tuple[str, date]:
    """Calculate the prior ISO week (week - 1) and return (prior_week_str, prior_monday)."""
    monday = date.fromisocalendar(year, week_num, 1)
    prior_monday = monday - timedelta(days=7)
    prior_iso = prior_monday.isocalendar()
    prior_week_str = f"{prior_iso.year:04d}-W{prior_iso.week:02d}"
    return prior_week_str, prior_monday


async def _fetch_meetings(
    session: AsyncSession, start_dt: datetime, end_dt: datetime
) -> list[Meeting]:
    """Fetch meetings starting within [start_dt, end_dt) with participants eagerly loaded."""
    stmt = (
        select(Meeting)
        .where(Meeting.starts_at >= start_dt, Meeting.starts_at < end_dt)
        .options(selectinload(Meeting.participants))
        .order_by(Meeting.starts_at.asc())
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def build_weekly_report_async(week: str, session: AsyncSession | None = None) -> bytes:
    """Async implementation of weekly report generation."""
    year, week_num = parse_iso_week(week)
    monday = date.fromisocalendar(year, week_num, 1)
    next_monday = monday + timedelta(days=7)

    prior_week_str, prior_monday = get_prior_iso_week(year, week_num)

    tz = settings.tz
    current_start = datetime.combine(monday, time.min, tzinfo=tz)
    current_end = datetime.combine(next_monday, time.min, tzinfo=tz)

    prior_start = datetime.combine(prior_monday, time.min, tzinfo=tz)
    prior_end = datetime.combine(monday, time.min, tzinfo=tz)

    async def _run_queries(sess: AsyncSession) -> bytes:
        current_meetings = await _fetch_meetings(sess, current_start, current_end)
        prior_meetings = await _fetch_meetings(sess, prior_start, prior_end)

        current_count = len(current_meetings)
        current_duration_hours = sum(
            max(0.0, (m.ends_at - m.starts_at).total_seconds() / 3600.0) for m in current_meetings
        )

        prior_count = len(prior_meetings)
        prior_duration_hours = sum(
            max(0.0, (m.ends_at - m.starts_at).total_seconds() / 3600.0) for m in prior_meetings
        )

        delta_count = current_count - prior_count
        delta_duration_hours = current_duration_hours - prior_duration_hours

        # Top 5 longest meetings in current week:
        # sorted by duration descending, then starts_at ascending
        top_5 = sorted(
            current_meetings,
            key=lambda m: (-(m.ends_at - m.starts_at).total_seconds(), m.starts_at),
        )[:5]

        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Summary Header & Rows
        writer.writerow(
            ["Metric", f"Current Week ({week})", f"Prior Week ({prior_week_str})", "Delta"]
        )
        delta_count_str = f"{delta_count:+d}" if delta_count != 0 else "0"
        writer.writerow(["Meeting Count", current_count, prior_count, delta_count_str])

        delta_dur_str = (
            f"{delta_duration_hours:+.2f}" if abs(delta_duration_hours) >= 1e-5 else "0.00"
        )
        writer.writerow(
            [
                "Total Duration (hours)",
                f"{current_duration_hours:.2f}",
                f"{prior_duration_hours:.2f}",
                delta_dur_str,
            ]
        )

        # Blank line separator
        writer.writerow([])

        # Top 5 Longest Meetings Table
        writer.writerow(["Title", "Start Time", "Duration (hours)", "Participant Count"])
        for m in top_5:
            duration_hrs = max(0.0, (m.ends_at - m.starts_at).total_seconds() / 3600.0)
            start_iso = m.starts_at.astimezone(tz).isoformat()
            writer.writerow([m.name, start_iso, f"{duration_hrs:.2f}", len(m.participants)])

        return output.getvalue().encode("utf-8")

    if session is not None:
        return await _run_queries(session)

    report_engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
    report_session_factory = async_sessionmaker(
        report_engine, expire_on_commit=False, autoflush=False
    )
    try:
        async with report_session_factory() as new_session:
            return await _run_queries(new_session)
    finally:
        await report_engine.dispose()


def build_weekly_report(week: str) -> bytes:
    """Pure Python function to build the weekly report for an ISO week string.

    Parameters:
        week: string in ISO format (e.g. '2026-W40').

    Returns:
        Formatted CSV as bytes.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Running inside an active event loop: delegate to worker thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, build_weekly_report_async(week)).result()

    return asyncio.run(build_weekly_report_async(week))
