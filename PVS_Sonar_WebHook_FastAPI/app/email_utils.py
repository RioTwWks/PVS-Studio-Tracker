import smtplib
from email.mime.text import MIMEText

from .config import settings

def send_email(subject: str, body: str, to_email: str = None):
    if to_email is None:
        to_email = settings.EMAIL_TO
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = settings.EMAIL_FROM
    msg['To'] = to_email

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.send_message(msg)
