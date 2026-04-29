"""NSE trading holiday calendar.

Source: NSE India `Trading Holidays` notice. Refreshed manually each January
and at every NSE circular. Sat/Sun handled by `app.timeutil.is_nse_holiday`,
so only weekday closures are listed here.
"""
from __future__ import annotations

from datetime import date

NSE_HOLIDAYS_2026: list[date] = [
    date(2026, 1, 26),  # Republic Day (Mon)
    date(2026, 2, 17),  # Mahashivratri (Tue)
    date(2026, 3, 4),   # Holi (Wed)
    date(2026, 3, 27),  # Good Friday (Fri)
    date(2026, 4, 1),   # Eid-Ul-Fitr (Wed)
    date(2026, 4, 14),  # Dr. B.R. Ambedkar Jayanti (Tue)
    date(2026, 5, 1),   # Maharashtra Day (Fri)
    date(2026, 5, 27),  # Eid-Ul-Adha (Wed)
    date(2026, 6, 26),  # Muharram (Fri)
    date(2026, 8, 17),  # Independence Day observed (Mon)
    date(2026, 8, 26),  # Ganesh Chaturthi (Wed)
    date(2026, 10, 2),  # Gandhi Jayanti (Fri)
    date(2026, 10, 19), # Mahatma Gandhi/Diwali Laxmi Pujan (Mon)
    date(2026, 11, 4),  # Guru Nanak Jayanti (Wed)
    date(2026, 12, 25), # Christmas (Fri)
]
