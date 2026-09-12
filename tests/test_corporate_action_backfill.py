from datetime import date

from src.reliability.corporate_action_backfill import backfill_pairs, monthly_ranges


class FakeResult:
    def __init__(self, request):
        self.status = "downloaded"
        self.request = request
        self.path = f"/{request.filename}"
        self.sha256 = "a" * 64
        self.byte_count = 10
        self.available_at = "2026-07-12T00:00:00Z"


class FakeAcquirer:
    def __init__(self):
        self.requests = []

    def acquire(self, request):
        self.requests.append(request)
        return FakeResult(request)


def test_monthly_ranges_clip_first_and_last_month():
    assert monthly_ranges(date(2024, 1, 15), date(2024, 3, 10)) == [
        (date(2024, 1, 15), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 10)),
    ]


def test_backfill_acquires_action_and_announcement_pair_for_each_month():
    acquirer = FakeAcquirer()
    sleeps = []

    result = backfill_pairs(
        acquirer,
        date(2024, 1, 1),
        date(2024, 2, 29),
        delay_seconds=0.5,
        sleep=sleeps.append,
    )

    assert [request.kind for request in acquirer.requests] == [
        "corporate_actions", "corporate_announcements",
        "corporate_actions", "corporate_announcements",
    ]
    assert len(result) == 4
    assert result[0]["period"] == "2024-01"
    assert sleeps == [0.5, 0.5, 0.5]
