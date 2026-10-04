import unittest

from app.research.price_window import recent_distinct_prices, session_return, canonical_prices


class RecentDistinctPricesTest(unittest.TestCase):
    def test_duplicate_providers_do_not_shorten_sixty_day_window(self):
        rows = [
            {"price_date": f"2026-08-{day:02d}", "source": source}
            for day in range(31, 0, -1)
            for source in ("twelvedata", "fmp")
        ] + [
            {"price_date": f"2026-07-{day:02d}", "source": "twelvedata"}
            for day in range(31, 0, -1)
        ]
        calls = []

        def fetch(offset, size):
            calls.append(offset)
            return rows[offset:offset + size]

        result = recent_distinct_prices(fetch, limit=60, page_size=50)
        self.assertEqual(len(result), 60)
        self.assertEqual(len({row["price_date"] for row in result}), 60)
        self.assertEqual(result[-1]["source"], "twelvedata")
        self.assertEqual(calls, [0, 50])

    def test_short_history_returns_available_dates(self):
        rows = [{"price_date": "2026-09-28"}, {"price_date": "2026-09-28"}]
        self.assertEqual(recent_distinct_prices(lambda offset, size: rows[offset:offset+size]), rows[:1])


if __name__ == "__main__":
    unittest.main()

def test_exact_session_label_does_not_shift_over_a_hole():
    days=[f'2026-08-{d:02d}' for d in range(1,8)]
    rows={d:{'close':100+i} for i,d in enumerate(days) if i!=5}
    assert session_return(rows,days,days[0],5) is None
    assert session_return(rows,days,days[0],10) is None
    assert session_return(rows,days,days[0],-1) is None
    assert session_return(rows,days,days[0],6)==106/100-1

def test_canonical_provider_priority_does_not_depend_on_response_order():
    rows=[{'company_id':1,'price_date':'2026-08-01','close':1,'source':'fmp'},
          {'company_id':1,'price_date':'2026-08-01','close':2,'source':'twelvedata'}]
    assert canonical_prices(rows)==canonical_prices(rows[::-1])==[rows[1]]
