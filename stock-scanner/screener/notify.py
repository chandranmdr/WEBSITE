"""Where alerts go. Secrets come from environment variables (or a .env file), never from config.yaml."""
from __future__ import annotations

import logging
import os
import platform
import shutil
import smtplib
import subprocess
from email.message import EmailMessage
from pathlib import Path

import requests

log = logging.getLogger(__name__)


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=value lines; existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


class Console:
    def send(self, title: str, text: str) -> None:
        print(text, flush=True)


class LogFile:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, title: str, text: str) -> None:
        with self.path.open("a") as f:
            f.write(text + "\n")


class Telegram:
    """Needs TELEGRAM_BOT_TOKEN (from @BotFather) and TELEGRAM_CHAT_ID."""

    def __init__(self):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = os.environ["TELEGRAM_CHAT_ID"]

    def send(self, title: str, text: str) -> None:
        requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                      json={"chat_id": self.chat_id, "text": text}, timeout=10).raise_for_status()


class Email:
    """Needs SMTP_HOST, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO (SMTP_PORT defaults to 587).

    For Gmail use smtp.gmail.com and an App Password, not your normal password.
    """

    def __init__(self):
        self.host = os.environ["SMTP_HOST"]
        self.port = int(os.environ.get("SMTP_PORT", "587"))
        self.user = os.environ["SMTP_USER"]
        self.password = os.environ["SMTP_PASSWORD"]
        self.to = os.environ["ALERT_EMAIL_TO"]

    def send(self, title: str, text: str) -> None:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = title, self.user, self.to
        msg.set_content(text)
        with smtplib.SMTP(self.host, self.port, timeout=20) as s:
            s.starttls()
            s.login(self.user, self.password)
            s.send_message(msg)


class Desktop:
    """Native pop-up: macOS (osascript) or Linux (notify-send)."""

    def send(self, title: str, text: str) -> None:
        body = text.split("\n", 1)[-1].strip()
        if platform.system() == "Darwin":
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
            subprocess.run(["osascript", "-e", f'display notification "{esc(body)}" with title "{esc(title)}" sound name "Glass"'], check=False)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", title, body], check=False)


class Notifier:
    """Fan out to every configured channel; one failing channel doesn't stop the others."""

    def __init__(self, channels: list[str], log_path: Path):
        self.sinks = []
        for name in channels:
            try:
                sink = {"console": Console, "telegram": Telegram, "email": Email, "desktop": Desktop}.get(name)
                if name == "logfile":
                    self.sinks.append(LogFile(log_path))
                elif sink is None:
                    log.warning("Unknown alert channel '%s'", name)
                else:
                    self.sinks.append(sink())
            except KeyError as missing:
                log.warning("Alert channel '%s' disabled: environment variable %s is not set", name, missing)

    def send(self, title: str, text: str) -> None:
        for sink in self.sinks:
            try:
                sink.send(title, text)
            except Exception as exc:  # noqa: BLE001
                log.warning("%s alert failed: %s", type(sink).__name__, exc)
