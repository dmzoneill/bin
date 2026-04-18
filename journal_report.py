import os
import subprocess
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests


class OpenAIProvider:

    def __init__(self) -> None:
        self.api_key: str = os.getenv("AI_API_KEY")
        self.endpoint: str = "https://api.openai.com/v1/chat/completions"
        self.model: str = os.getenv("AI_MODEL", "gpt-4")

    def improve_text(self, prompt: str, text: str) -> str:
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.4,
        }

        try:
            response: requests.Response = requests.post(
                self.endpoint, json=body, headers=headers, timeout=120
            )

            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"].strip()

            raise Exception(
                f"OpenAI API call failed: {response.status_code} - {response.text}"
            )
        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {str(e)}")


def get_journal_logs() -> str:
    result = subprocess.run(
        ["journalctl", "--since", "today", "--output", "short-iso"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        text=True,
    )
    return result.stdout


def save_logs_to_file(logs: str, filepath: str):
    with open(filepath, "w") as f:
        f.write(logs)


def generate_prompt() -> str:
    return (
        "You are a Linux system administrator analyzing systemd journal logs from today. "
        "The logs are hosted at the following URL: https://www.feeditout.com/journal.txt\n\n"
        "Download or assume access to the logs and produce a well-formatted HTML report "
        "summarizing issues, warnings, errors, and service failures. Group items by category "
        "using <h2> headings and <ul> lists. Focus on actionable insights, recurring patterns, "
        "and resolution suggestions where possible."
    )


def send_email(subject: str, html_body: str, to_address: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = os.getenv("EMAIL_FROM", "server@localhost")
    msg["To"] = to_address

    part = MIMEText(html_body, "html")
    msg.attach(part)

    with smtplib.SMTP("localhost") as server:
        server.sendmail(msg["From"], [to_address], msg.as_string())


def main():
    try:
        print("📥 Fetching logs...")
        logs = get_journal_logs()

        print("💾 Saving logs to /home/dave/feeditout.com/journal.txt...")
        save_logs_to_file(logs, "/home/dave/feeditout.com/journal.txt")

        print("🧠 Sending prompt to OpenAI...")
        ai = OpenAIProvider()
        prompt = generate_prompt()
        html_report = ai.improve_text(prompt, "")

        print("📧 Sending email...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        subject = f"System Log Report - {today_str}"
        send_email(subject, html_report, "dmz.oneill@gmail.com")

        print("✅ Done. Email sent.")
    except Exception as e:
        print(f"❌ Failed: {e}")


if __name__ == "__main__":
    main()

