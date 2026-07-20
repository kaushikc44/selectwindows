# tests/test_poller.py
from email.message import EmailMessage

from app.ingest.poller import poll_inbox


class FakeIMAP:
    def __init__(self, messages: dict[bytes, bytes]):
        self._messages = messages
        self.stored_seen: list[bytes] = []
        self.logged_out = False

    def search(self, _charset, _criteria):
        return "OK", [b" ".join(self._messages.keys())]

    def fetch(self, num, _parts):
        raw = self._messages[num]
        return "OK", [(b"%b (RFC822 {%d}" % (num, len(raw)), raw), b")"]

    def store(self, num, _flag_op, _flags):
        self.stored_seen.append(num)
        return "OK", [b"1"]

    def logout(self):
        self.logged_out = True


def _image_email(message_id: str, from_addr: str = "worker@example.com") -> bytes:
    msg = EmailMessage()
    msg["Message-ID"] = message_id
    msg["From"] = from_addr
    msg["Subject"] = "W1 measurement"
    msg.set_content("See attached photo.")
    msg.add_attachment(b"\xff\xd8\xff\xe0fakejpegbytes", maintype="image", subtype="jpeg", filename="w1.jpg")
    return bytes(msg)


def _text_only_email(message_id: str, from_addr: str = "worker@example.com") -> bytes:
    msg = EmailMessage()
    msg["Message-ID"] = message_id
    msg["From"] = from_addr
    msg["Subject"] = "question"
    msg.set_content("No photo attached, just a question.")
    return bytes(msg)


def test_image_attachment_is_saved_and_message_marked_seen(tmp_path):
    fake = FakeIMAP({b"1": _image_email("<img-1@example.com>")})

    results = poll_inbox(storage_dir=tmp_path, client=fake)

    assert len(results) == 1
    saved = results[0]
    assert saved.email_message_id == "<img-1@example.com>"
    assert saved.content_type == "image/jpeg"
    assert (tmp_path / saved.filename).exists()
    assert (tmp_path / saved.filename).read_bytes().startswith(b"\xff\xd8\xff")
    assert fake.stored_seen == [b"1"]
    assert fake.logged_out is False  # injected client is not owned/closed by poll_inbox


def test_non_image_email_is_skipped_and_logged(tmp_path, caplog):
    fake = FakeIMAP({b"1": _text_only_email("<text-1@example.com>")})

    with caplog.at_level("INFO"):
        results = poll_inbox(storage_dir=tmp_path, client=fake)

    assert results == []
    assert fake.stored_seen == [b"1"]  # still marked seen so it isn't re-polled forever
    assert any("Skipping non-image email" in record.message for record in caplog.records)


def test_mixed_inbox_only_saves_image_attachment(tmp_path):
    fake = FakeIMAP(
        {
            b"1": _text_only_email("<text-1@example.com>"),
            b"2": _image_email("<img-2@example.com>"),
        }
    )

    results = poll_inbox(storage_dir=tmp_path, client=fake)

    assert len(results) == 1
    assert results[0].email_message_id == "<img-2@example.com>"
    assert sorted(fake.stored_seen) == [b"1", b"2"]


def test_empty_inbox_returns_no_results():
    fake = FakeIMAP({})

    results = poll_inbox(storage_dir=None, client=fake)

    assert results == []
