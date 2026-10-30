#!/usr/bin/env python3
"""Email an HTML summary of today's systemd journal."""

import os
import smtplib
import subprocess  # nosec B404
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from binlib import OpenAIError, journal_openai


def get_journal_logs() -> str:
    """Return today's journalctl output."""
    result = subprocess.run(  # nosec B603 B607
        ["journalctl", "--since", "today", "--output", "short-iso"],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout


def save_logs_to_file(logs: str, filepath: str) -> None:
    """Write the journal text to ``filepath``."""
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(logs)


def generate_prompt() -> str:
    """Build the system prompt that asks for an HTML report."""
    journal_url = os.getenv("JOURNAL_URL", "https://www.feeditout.com/journal.txt")
    return (
        "You are a Linux system administrator analyzing systemd journal logs from today. "
        f"The logs are hosted at the following URL: {journal_url}\n\n"
        "Download or assume access to the logs and produce a well-formatted HTML report "
        "summarizing issues, warnings, errors, and service failures. Group items by category "
        "using <h2> headings and <ul> lists. Focus on actionable insights, recurring patterns, "
        "and resolution suggestions where possible."
    )


def send_email(subject: str, html_body: str, to_address: str) -> None:
    """Send ``html_body`` through the configured SMTP server."""
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = os.getenv("EMAIL_FROM", "server@localhost")
    message["To"] = to_address
    message.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(os.getenv("SMTP_HOST", "localhost")) as server:
        server.sendmail(message["From"], [to_address], message.as_string())


def main() -> None:
    """Collect today's logs, ask OpenAI for a report, and email it."""
    try:
        print("📥 Fetching logs...")
        logs = get_journal_logs()
        journal_path = os.getenv(
            "JOURNAL_OUTPUT_PATH",
            os.path.expanduser("~/feeditout.com/journal.txt"),
        )
        print(f"💾 Saving logs to {journal_path}...")
        save_logs_to_file(logs, journal_path)
        print("🧠 Sending prompt to OpenAI...")
        html_report = journal_openai().improve_text(generate_prompt(), "")
        print("📧 Sending email...")
        today_str = datetime.now().astimezone().strftime("%Y-%m-%d")
        subject = f"System Log Report - {today_str}"
        send_email(
            subject,
            html_report,
            os.getenv("REPORT_EMAIL", "dmz.oneill@gmail.com"),
        )
        print("✅ Done. Email sent.")
    except (
        OSError,
        subprocess.SubprocessError,
        smtplib.SMTPException,
        OpenAIError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ) as exc:
        print(f"❌ Failed: {exc}")


if __name__ == "__main__":
    main()
