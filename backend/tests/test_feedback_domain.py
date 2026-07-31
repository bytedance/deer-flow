"""Pure unit tests for the Feedback aggregate — zero IO, no engine."""

import pytest

from deerflow.domain.feedback import Feedback, InvalidRatingError, InvalidTagError


class TestFeedbackAggregate:
    def test_factory_generates_identity(self):
        fb = Feedback.create(run_id="r1", thread_id="t1", rating=1)
        assert fb.feedback_id
        assert fb.run_id == "r1"
        assert fb.thread_id == "t1"

    def test_factory_distinct_identities(self):
        a = Feedback.create(run_id="r1", thread_id="t1", rating=1)
        b = Feedback.create(run_id="r1", thread_id="t1", rating=1)
        assert a.feedback_id != b.feedback_id

    def test_created_at_is_tz_aware(self):
        fb = Feedback.create(run_id="r1", thread_id="t1", rating=1)
        assert fb.created_at.tzinfo is not None

    @pytest.mark.parametrize("rating", [0, 5, -2, 2])
    def test_invalid_rating_raises_before_any_io(self, rating):
        with pytest.raises(InvalidRatingError):
            Feedback.create(run_id="r1", thread_id="t1", rating=rating)

    @pytest.mark.parametrize("rating", [1, -1])
    def test_valid_ratings(self, rating):
        assert Feedback.create(run_id="r1", thread_id="t1", rating=rating).rating == rating

    def test_valid_tags_accepted(self):
        fb = Feedback.create(run_id="r1", thread_id="t1", rating=-1, tags=["incorrect", "slow"])
        assert fb.tags == ("incorrect", "slow")

    def test_unknown_tag_rejected(self):
        with pytest.raises(InvalidTagError):
            Feedback.create(run_id="r1", thread_id="t1", rating=-1, tags=["bogus"])

    def test_direct_construction_also_validates(self):
        # Invariants live on the aggregate, not only on the factory.
        with pytest.raises(InvalidRatingError):
            Feedback(feedback_id="x", run_id="r1", thread_id="t1", rating=0)

    def test_frozen(self):
        fb = Feedback.create(run_id="r1", thread_id="t1", rating=1)
        with pytest.raises(AttributeError):
            fb.rating = -1  # type: ignore[misc]
