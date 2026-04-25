import pytest
from rfnry_chat_protocol import AssistantIdentity, UserIdentity

from rfnry_chat_client.mentions import parse_member_mentions


@pytest.fixture
def members():
    return [
        AssistantIdentity(id="agent-a", name="Agent A"),
        AssistantIdentity(id="agent-b", name="Agent B"),
        UserIdentity(id="u_alice", name="Alice"),
        UserIdentity(id="u_bob", name="Bobby Smith"),
    ]


def test_single_word_name(members):
    p = parse_member_mentions("@Alice hi", members)
    assert p.recipients == ["u_alice"]
    assert p.body == "hi"


def test_multi_word_name(members):
    p = parse_member_mentions("@Agent A what is up?", members)
    assert p.recipients == ["agent-a"]
    assert p.body == "what is up?"


def test_id_form(members):
    p = parse_member_mentions("@agent-b take this", members)
    assert p.recipients == ["agent-b"]
    assert p.body == "take this"


def test_multi_word_with_trailing_punct(members):
    p = parse_member_mentions("@Bobby Smith, please review", members)
    assert p.recipients == ["u_bob"]


def test_two_mentions_dedup(members):
    p = parse_member_mentions("@Agent A and @Agent A again", members)
    assert p.recipients == ["agent-a"]
    assert len(p.spans) == 2


def test_unknown_dropped(members):
    p = parse_member_mentions("@Nobody hi", members)
    assert p.recipients == []


def test_longest_match_wins():
    members = [
        AssistantIdentity(id="agent", name="Agent"),
        AssistantIdentity(id="agent-a", name="Agent A"),
    ]
    p = parse_member_mentions("@Agent A hi", members)
    assert p.recipients == ["agent-a"]


def test_here_expansion(members):
    p = parse_member_mentions("@here ping", members, roles=["assistant"])
    assert set(p.recipients) == {"agent-a", "agent-b"}


def test_boundary_respected(members):
    p = parse_member_mentions("@AliceBoo", members)
    assert p.recipients == []


def test_no_email_match(members):
    p = parse_member_mentions("foo@Alice", members)
    # The @ is preceded by 'o' which isn't a boundary — must not match.
    assert p.recipients == []


def test_body_strips_leading_mentions(members):
    p = parse_member_mentions("@Agent A @Agent B do this", members)
    assert p.recipients == ["agent-a", "agent-b"]
    assert p.body == "do this"


def test_body_keeps_mid_text_mentions(members):
    p = parse_member_mentions("hey @Agent A check this", members)
    assert p.recipients == ["agent-a"]
    assert p.body == "hey @Agent A check this"  # leading is "hey", no strip
