"""
Multi-world lobbies: bot_launcher answers the world prompt from IKABOT_WORLD.
With a saved session the queued password must not be read as the world number.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot_launcher as bl


def test_fresh_login_keeps_password_and_appends_world():
    q = ["mail@example.com", "secret"]
    assert bl._queue_world_choice(q, "2", has_saved_session=False) == ["mail@example.com", "secret", 2]


def test_saved_session_drops_password_before_world():
    q = ["mail@example.com", "secret"]
    assert bl._queue_world_choice(q, "1", has_saved_session=True) == ["mail@example.com", 1]


def test_unset_or_invalid_world_leaves_queue_untouched():
    for value in (None, "", "abc", "0", "-1"):
        q = ["mail@example.com", "secret"]
        assert bl._queue_world_choice(q, value, has_saved_session=True) == ["mail@example.com", "secret"]


def test_world_value_is_stripped():
    q = ["mail@example.com"]
    assert bl._queue_world_choice(q, " 3 ", has_saved_session=False) == ["mail@example.com", 3]


def test_has_saved_session_fallback_without_ikabot(monkeypatch, tmp_path):
    users = tmp_path / ".ikabot" / "users"
    users.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setitem(sys.modules, "ikabot.helpers.sessionStorage", None)
    assert bl._has_saved_session("mail@example.com") is False
    (users / "mail.json").write_text("{}")
    assert bl._has_saved_session("mail@example.com") is True
