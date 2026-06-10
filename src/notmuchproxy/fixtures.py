"""Generate a small maildir + notmuch database for tests and local dev.

Usage: python -m notmuchproxy.fixtures <dest-dir>

Creates <dest-dir>/mail (a maildir indexed by notmuch — point NOTMUCH_DATABASE
at it) and <dest-dir>/notmuch-config (used only while indexing/tagging).
"""

import mailbox
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

PRIMARY_EMAIL = "user@example.com"


def _email(
    *,
    subject: str,
    sender: str,
    to: str,
    date: datetime,
    message_id: str,
    in_reply_to: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = format_datetime(date)
    msg["Message-ID"] = f"<{message_id}>"
    if in_reply_to:
        msg["In-Reply-To"] = f"<{in_reply_to}>"
        msg["References"] = f"<{in_reply_to}>"
    return msg


def _build_messages() -> list[EmailMessage]:
    messages: list[EmailMessage] = []

    # a three-message thread
    planning = _email(
        subject="Quarterly planning",
        sender="Alice Anderson <alice@example.com>",
        to=f"team@example.com, {PRIMARY_EMAIL}",
        date=datetime(2024, 1, 15, 9, 0, tzinfo=UTC),
        message_id="planning-1@example.com",
    )
    planning.set_content("Hi team,\n\nLet's plan Q1. Ideas in the doc by Friday please.\n\nAlice")
    messages.append(planning)

    reply1 = _email(
        subject="Re: Quarterly planning",
        sender="Bob Brown <bob@example.com>",
        to="alice@example.com, team@example.com",
        date=datetime(2024, 1, 15, 11, 30, tzinfo=UTC),
        message_id="planning-2@example.com",
        in_reply_to="planning-1@example.com",
    )
    reply1.set_content("Added my ideas: focus on the search latency project.\n\nBob")
    messages.append(reply1)

    reply2 = _email(
        subject="Re: Quarterly planning",
        sender="Carol Clark <carol@example.com>",
        to="alice@example.com, team@example.com",
        date=datetime(2024, 1, 16, 8, 15, tzinfo=UTC),
        message_id="planning-3@example.com",
        in_reply_to="planning-2@example.com",
    )
    reply2.set_content("+1 to Bob. I'll draft the milestones.\n\nCarol")
    messages.append(reply2)

    # an invoice with an attachment
    invoice = _email(
        subject="Invoice #1234 for January",
        sender="Billing <billing@example.com>",
        to=PRIMARY_EMAIL,
        date=datetime(2024, 2, 1, 12, 0, tzinfo=UTC),
        message_id="invoice-1234@example.com",
    )
    invoice.set_content("Your invoice #1234 for $42.00 is attached.\n\nThanks!")
    invoice.add_attachment(
        b"%PDF-1.4 fake invoice content",
        maintype="application",
        subtype="pdf",
        filename="invoice-1234.pdf",
    )
    messages.append(invoice)

    # an html-only newsletter
    newsletter = _email(
        subject="Weekly newsletter: shiny things",
        sender="News <news@example.com>",
        to=PRIMARY_EMAIL,
        date=datetime(2024, 2, 5, 6, 0, tzinfo=UTC),
        message_id="newsletter-7@example.com",
    )
    newsletter.add_alternative(
        "<html><head><style>p { color: red; }</style></head>"
        "<body><h1>Shiny things</h1><p>This week we cover <b>three</b> shiny things.</p>"
        "</body></html>",
        subtype="html",
    )
    messages.append(newsletter)

    # a plain standalone message
    lunch = _email(
        subject="Lunch tomorrow?",
        sender="Dave Diaz <dave@example.com>",
        to=PRIMARY_EMAIL,
        date=datetime(2024, 2, 10, 17, 45, tzinfo=UTC),
        message_id="lunch-1@example.com",
    )
    lunch.set_content("Tacos at noon?")
    messages.append(lunch)

    return messages


def create_archive(dest: Path) -> Path:
    """Build the maildir under dest/mail, index it, and return the mail root."""
    dest = dest.resolve()
    mail_root = dest / "mail"
    if mail_root.exists():
        shutil.rmtree(mail_root)

    maildir = mailbox.Maildir(str(mail_root))
    for msg in _build_messages():
        maildir.add(mailbox.MaildirMessage(msg))

    config = dest / "notmuch-config"
    config.write_text(
        f"[database]\npath={mail_root}\n"
        "[new]\ntags=inbox;unread\n"
        f"[user]\nname=Test User\nprimary_email={PRIMARY_EMAIL}\n"
        "[maildir]\nsynchronize_flags=true\n"
    )

    def notmuch(*args: str) -> None:
        subprocess.run(
            ["notmuch", f"--config={config}", *args],
            check=True,
            capture_output=True,
            text=True,
        )

    notmuch("new")
    notmuch("tag", "+billing", "--", "subject:invoice")
    notmuch("tag", "+newsletter", "--", "from:news@example.com")

    return mail_root


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = create_archive(Path(sys.argv[1]))
    print(f"notmuch archive ready at {root}")
