from rfnry_chat_client.mentions import parse_mention_ids

MEMBERS = {"engineer", "coordinator", "liaison", "u_alice", "u_bob"}


def test_single_mention_at_start() -> None:
    assert parse_mention_ids("@engineer hello", MEMBERS) == ["engineer"]


def test_single_mention_at_end() -> None:
    assert parse_mention_ids("hello @engineer", MEMBERS) == ["engineer"]


def test_single_mention_only() -> None:
    assert parse_mention_ids("@engineer", MEMBERS) == ["engineer"]


def test_two_distinct_mentions() -> None:
    assert parse_mention_ids("@engineer and @coordinator", MEMBERS) == ["engineer", "coordinator"]


def test_dedup_preserves_first_seen_order() -> None:
    assert parse_mention_ids("@engineer @coordinator @engineer", MEMBERS) == ["engineer", "coordinator"]


def test_trailing_comma_trimmed() -> None:
    assert parse_mention_ids("@engineer, please review", MEMBERS) == ["engineer"]


def test_trailing_period_trimmed() -> None:
    assert parse_mention_ids("ping @engineer.", MEMBERS) == ["engineer"]


def test_trailing_question_mark_trimmed() -> None:
    assert parse_mention_ids("@engineer?", MEMBERS) == ["engineer"]


def test_multiple_trailing_punct_trimmed() -> None:
    assert parse_mention_ids("@engineer!!!", MEMBERS) == ["engineer"]


def test_unknown_id_dropped() -> None:
    assert parse_mention_ids("@nobody hi", MEMBERS) == []


def test_partial_token_with_dot_does_not_match() -> None:
    assert parse_mention_ids("contact @engineer.com please", MEMBERS) == []


def test_no_at_no_match() -> None:
    assert parse_mention_ids("hello world", MEMBERS) == []


def test_at_followed_by_whitespace_no_match() -> None:
    assert parse_mention_ids("hello @ world", MEMBERS) == []


def test_id_with_underscore_works() -> None:
    assert parse_mention_ids("@u_alice ping", MEMBERS) == ["u_alice"]


def test_case_sensitive_id_lookup() -> None:
    assert parse_mention_ids("@Engineer hello", MEMBERS) == []


def test_mid_word_at_permissive_match() -> None:

    assert parse_mention_ids("foo@engineer", MEMBERS) == ["engineer"]


def test_empty_text() -> None:
    assert parse_mention_ids("", MEMBERS) == []


def test_only_at_symbol() -> None:
    assert parse_mention_ids("@", MEMBERS) == []


def test_only_at_followed_by_punct() -> None:
    assert parse_mention_ids("@,", MEMBERS) == []


def test_consecutive_at_symbols_no_match() -> None:

    assert parse_mention_ids("@@engineer", MEMBERS) == []


def test_only_whitespace() -> None:
    assert parse_mention_ids("   \t\n  ", MEMBERS) == []


def test_mention_followed_by_newline() -> None:
    assert parse_mention_ids("@engineer\nplease check", MEMBERS) == ["engineer"]


def test_mention_followed_by_tab() -> None:
    assert parse_mention_ids("@engineer\there", MEMBERS) == ["engineer"]


def test_three_distinct_mentions() -> None:
    assert parse_mention_ids(
        "@engineer @coordinator @liaison all please look",
        MEMBERS,
    ) == ["engineer", "coordinator", "liaison"]


def test_each_trim_punct_individually() -> None:
    for punct in ",.!?;:)]}'\"":
        text = f"hi @engineer{punct}"
        assert parse_mention_ids(text, MEMBERS) == ["engineer"], f"failed for trailing {punct!r}"


def test_combined_trailing_punct() -> None:
    assert parse_mention_ids("@engineer!?...", MEMBERS) == ["engineer"]


def test_leading_punct_not_part_of_token() -> None:

    assert parse_mention_ids("(@engineer)", MEMBERS) == ["engineer"]


def test_unicode_in_id_preserved() -> None:
    members = {"alice", "bob", "lîaîson"}
    assert parse_mention_ids("@lîaîson hello", members) == ["lîaîson"]


def test_id_immediately_followed_by_id_no_match() -> None:

    assert parse_mention_ids("@engineer@coordinator", MEMBERS) == []


def test_mention_with_query_args_no_match() -> None:
    assert parse_mention_ids("@engineer?key=value", MEMBERS) == []


def test_handles_very_long_text_with_mentions() -> None:
    long_prefix = "lorem ipsum " * 100
    text = f"{long_prefix}@engineer please look"
    assert parse_mention_ids(text, MEMBERS) == ["engineer"]


def test_hundred_member_lookup() -> None:
    big_set = {f"u_{i:03d}" for i in range(100)} | {"engineer"}
    assert parse_mention_ids("@engineer @u_042 hi", big_set) == ["engineer", "u_042"]


def test_returns_new_list_each_call() -> None:
    a = parse_mention_ids("@engineer", MEMBERS)
    a.append("mutated")
    b = parse_mention_ids("@engineer", MEMBERS)
    assert b == ["engineer"]


def test_member_ids_set_not_mutated() -> None:
    members = {"engineer", "coordinator"}
    snapshot = set(members)
    parse_mention_ids("@engineer @coordinator @unknown", members)
    assert members == snapshot


def test_empty_member_set() -> None:
    assert parse_mention_ids("@engineer hello", set()) == []


def test_mention_inside_parentheses_then_text() -> None:

    assert parse_mention_ids("see (@engineer) for review", MEMBERS) == ["engineer"]


def test_mention_with_trailing_apostrophe() -> None:

    assert parse_mention_ids("@engineer's note", MEMBERS) == []


def test_apostrophe_only_trailing_trimmed() -> None:

    assert parse_mention_ids("@engineer'", MEMBERS) == ["engineer"]


def test_quote_only_trailing_trimmed() -> None:
    assert parse_mention_ids('"@engineer"', MEMBERS) == ["engineer"]
