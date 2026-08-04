"""Unit contracts for local streaming content safety checks."""

from deerflow.safety.streaming_guard import BLOCKED_RESPONSE_TEXT, RuleSet, StreamingContentGuard


def test_guard_detects_a_rule_split_between_stream_chunks():
    guard = StreamingContentGuard(RuleSet.from_terms(["forbidden phrase"]), window_chars=80)

    first_verdict, first_release = guard.push_output("forbidden ")
    verdict, released = guard.push_output("phrase")

    assert not first_verdict.blocked
    assert first_release == []
    assert verdict.blocked
    assert released == []
    assert verdict.user_message == BLOCKED_RESPONSE_TEXT


def test_guard_releases_safe_text_only_after_the_buffer_window():
    guard = StreamingContentGuard(RuleSet.from_terms(["forbidden"]), window_chars=5)

    verdict, released = guard.push_output("abcdef")

    assert not verdict.blocked
    assert "".join(released) == "a"
    assert "".join(guard.flush()) == "bcdef"


def test_input_detection_does_not_depend_on_output_buffering():
    guard = StreamingContentGuard(RuleSet.from_terms(["forbidden phrase"]), window_chars=80)

    verdict = guard.inspect_input("please provide a forbidden phrase")

    assert verdict.blocked
    assert verdict.redacted_excerpt == "please provide a for***"
