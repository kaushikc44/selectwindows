# tests/test_poller.py
from email.message import EmailMessage

from app.ingest.poller import PROCESSED_FLAG, _search_query, _strip_quoted_reply, poll_inbox, poll_replies


class FakeIMAP:
    def __init__(self, messages: dict[bytes, bytes]):
        self._messages = messages
        self.stored_flags: list[tuple[bytes, str]] = []
        self.logged_out = False
        self.searched_criteria: list[str] = []

    def search(self, _charset, criteria):
        self.searched_criteria.append(criteria)
        return "OK", [b" ".join(self._messages.keys())]

    def fetch(self, num, _parts):
        raw = self._messages[num]
        return "OK", [(b"%b (RFC822 {%d}" % (num, len(raw)), raw), b")"]

    def store(self, num, _flag_op, flags):
        self.stored_flags.append((num, flags))
        return "OK", [b"1"]

    def logout(self):
        self.logged_out = True

    @property
    def stored_seen(self) -> list[bytes]:
        return [num for num, _flags in self.stored_flags]


def _image_email(
    message_id: str, body: str = "bi-fold window, aluminium, laundry", from_addr: str = "worker@example.com"
) -> bytes:
    msg = EmailMessage()
    msg["Message-ID"] = message_id
    msg["From"] = from_addr
    msg["Subject"] = "select windows quote"
    msg.set_content(body)
    msg.add_attachment(b"\xff\xd8\xff\xe0fakejpegbytes", maintype="image", subtype="jpeg", filename="opening.jpg")
    return bytes(msg)


def _multi_image_email(message_id: str, from_addr: str = "worker@example.com") -> bytes:
    msg = EmailMessage()
    msg["Message-ID"] = message_id
    msg["From"] = from_addr
    msg["Subject"] = "select windows quote"
    msg.set_content("bi-fold window laundry, sliding door kitchen")
    msg.add_attachment(b"page1bytes", maintype="image", subtype="jpeg", filename="opening1.jpg")
    msg.add_attachment(b"page2bytes", maintype="image", subtype="jpeg", filename="opening2.jpg")
    return bytes(msg)


def _text_only_email(message_id: str, from_addr: str = "worker@example.com") -> bytes:
    msg = EmailMessage()
    msg["Message-ID"] = message_id
    msg["From"] = from_addr
    msg["Subject"] = "question"
    msg.set_content("No photo attached, just a question.")
    return bytes(msg)


def test_image_email_saved_with_body_text_and_message_marked_processed(tmp_path):
    fake = FakeIMAP({b"1": _image_email("<img-1@example.com>")})

    results = poll_inbox(storage_dir=tmp_path, client=fake)

    assert len(results) == 1
    message = results[0]
    assert message.email_message_id == "<img-1@example.com>"
    assert message.body_text == "bi-fold window, aluminium, laundry"
    assert len(message.images) == 1
    assert message.images[0].content_type == "image/jpeg"
    assert (tmp_path / message.images[0].filename).exists()
    assert (tmp_path / message.images[0].filename).read_bytes().startswith(b"\xff\xd8\xff")
    assert fake.stored_seen == [b"1"]
    assert fake.logged_out is False  # injected client is not owned/closed by poll_inbox


def test_processed_marker_sets_both_seen_and_custom_flag(tmp_path):
    fake = FakeIMAP({b"1": _image_email("<img-1@example.com>")})

    poll_inbox(storage_dir=tmp_path, client=fake)

    _num, flags = fake.stored_flags[0]
    assert "\\Seen" in flags
    assert PROCESSED_FLAG in flags


def test_search_query_gates_on_custom_flag_not_seen():
    query = _search_query()
    assert f"UNKEYWORD {PROCESSED_FLAG}" in query
    assert "UNSEEN" not in query  # reading the email yourself must not hide it from future polls


def test_multiple_photos_in_one_email_are_all_collected(tmp_path):
    fake = FakeIMAP({b"1": _multi_image_email("<img-multi@example.com>")})

    results = poll_inbox(storage_dir=tmp_path, client=fake)

    assert len(results) == 1
    assert len(results[0].images) == 2
    filenames = {img.filename.split("_", 1)[1] for img in results[0].images}
    assert filenames == {"opening1.jpg", "opening2.jpg"}


def test_non_image_email_is_skipped_and_logged(tmp_path, caplog):
    fake = FakeIMAP({b"1": _text_only_email("<text-1@example.com>")})

    with caplog.at_level("INFO"):
        results = poll_inbox(storage_dir=tmp_path, client=fake)

    assert results == []
    assert fake.stored_seen == [b"1"]  # still marked processed so it isn't re-polled forever
    assert any("Skipping non-image email" in record.message for record in caplog.records)


def test_mixed_inbox_only_returns_image_email(tmp_path):
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


def test_strip_quoted_reply_removes_gmail_style_quote_block():
    body = (
        "Hinged is the product type\n\n"
        "On Wed, 22 Jul 2026 at 12:24 pm, <kaushikc44@gmail.com> wrote:\n\n"
        "> Thanks for the photos! To finish this quote we just need:\n"
        ">\n"
        "> - the product type — one of these exact words — windows: awning, casement,\n"
        "> sliding, double hung, louvre, powerlouvre, bi-fold, sashless, gas strut;\n"
        "> doors: sliding, stacking, bi-fold, hinged, cedar entry\n"
        ">\n"
        "> Just reply to this email with those details and we'll continue.\n"
        ">\n"
    )
    assert _strip_quoted_reply(body) == "Hinged is the product type"


def test_strip_quoted_reply_leaves_plain_body_unchanged():
    assert _strip_quoted_reply("bi-fold window, aluminium, laundry") == "bi-fold window, aluminium, laundry"


def test_strip_quoted_reply_drops_leading_gt_lines_without_attribution_line():
    body = "Sarah Nguyen\n> quoted junk without an On...wrote header\n> more junk"
    assert _strip_quoted_reply(body) == "Sarah Nguyen"


def _reply_email(message_id: str, in_reply_to: str, body: str, from_addr: str = "rep@fieldcrew.example.com") -> bytes:
    msg = EmailMessage()
    msg["Message-ID"] = message_id
    msg["In-Reply-To"] = in_reply_to
    msg["From"] = from_addr
    msg["Subject"] = "Re: Quick info needed for your quote request"
    msg.set_content(body)
    return bytes(msg)


def test_poll_replies_returns_empty_list_when_no_awaiting_ids(tmp_path):
    fake = FakeIMAP({})
    assert poll_replies(set(), storage_dir=tmp_path, client=fake) == []
    assert fake.searched_criteria == []  # no IMAP round trip at all


def test_poll_replies_does_exactly_one_search_regardless_of_awaiting_count(tmp_path):
    original_id = "<clarify-1@select.example.com>"
    reply_bytes = _reply_email("<reply-1@fieldcrew.example.com>", original_id, "It's a bi-fold window for Sarah Nguyen")
    fake = FakeIMAP({b"5": reply_bytes})

    poll_replies({original_id, "<clarify-2@x>", "<clarify-3@x>"}, storage_dir=tmp_path, client=fake)

    assert len(fake.searched_criteria) == 1
    assert "Quick info needed" in fake.searched_criteria[0]


def test_poll_replies_matches_via_in_reply_to_header(tmp_path):
    original_id = "<clarify-1@select.example.com>"
    reply_bytes = _reply_email("<reply-1@fieldcrew.example.com>", original_id, "It's a bi-fold window for Sarah Nguyen")
    fake = FakeIMAP({b"5": reply_bytes})

    results = poll_replies({original_id}, storage_dir=tmp_path, client=fake)

    assert len(results) == 1
    assert results[0].in_reply_to == original_id
    assert results[0].from_address == "rep@fieldcrew.example.com"
    assert "bi-fold window" in results[0].body_text
    assert fake.stored_seen == [b"5"]


def test_poll_replies_ignores_and_marks_processed_messages_not_matching_any_awaiting_id(tmp_path):
    reply_bytes = _reply_email("<reply-1@fieldcrew.example.com>", "<some-other-thread@x>", "unrelated reply")
    fake = FakeIMAP({b"9": reply_bytes})

    results = poll_replies({"<clarify-1@select.example.com>"}, storage_dir=tmp_path, client=fake)

    assert results == []
    assert fake.stored_seen == [b"9"]  # marked processed so it isn't refetched every poll


def test_poll_replies_collects_images_if_rep_attaches_one(tmp_path):
    original_id = "<clarify-2@select.example.com>"
    msg = EmailMessage()
    msg["Message-ID"] = "<reply-2@fieldcrew.example.com>"
    msg["In-Reply-To"] = original_id
    msg["From"] = "rep@fieldcrew.example.com"
    msg.set_content("here's a clearer photo")
    msg.add_attachment(b"\xff\xd8\xff\xe0fakejpeg", maintype="image", subtype="jpeg", filename="clearer.jpg")

    fake = FakeIMAP({b"7": bytes(msg)})

    results = poll_replies({original_id}, storage_dir=tmp_path, client=fake)

    assert len(results[0].images) == 1
    assert results[0].images[0].filename.endswith("clearer.jpg")
