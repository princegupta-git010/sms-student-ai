
from sqlalchemy import select

from database import SessionLocal
from models import TimetableEntry

# Times use 24-hour format.
# The script skips entries that already exist exactly.

schedule = [
    # Monday
    ("Monday", "HCL Training", "09:40", "13:10", ""),
    ("Monday", "Python Programming (PP)", "13:50", "14:30", ""),
    ("Monday", "Digital Electronics (DE)", "14:30", "15:10", ""),
    ("Monday", "Aptitude (APT)", "15:10", "15:50", ""),

    # Tuesday
    ("Tuesday", "Python Programming (PP)", "09:40", "10:40", ""),
    ("Tuesday", "Computer Organization & Architecture (COA)", "10:40", "11:40", ""),
    ("Tuesday", "Digital Electronics (DE)", "11:40", "12:25", ""),
    ("Tuesday", "Technical Communication (TC)", "12:25", "13:10", ""),
    ("Tuesday", "Python Programming (PP)", "13:50", "14:30", ""),
    ("Tuesday", "Computer Organization & Architecture (COA)", "14:30", "15:10", ""),
    ("Tuesday", "Discrete Structures & Theory of Logic (DSTL)", "15:10", "15:50", ""),

    # Wednesday
    ("Wednesday", "HCL Training", "09:40", "13:10", ""),
    ("Wednesday", "Digital Electronics (DE)", "13:50", "14:30", ""),
    ("Wednesday", "Computer Organization & Architecture (COA)", "14:30", "15:10", ""),
    ("Wednesday", "Discrete Structures & Theory of Logic (DSTL)", "15:10", "15:50", ""),

    # Thursday
    ("Thursday", "Python Programming (PP)", "09:40", "10:40", ""),
    ("Thursday", "Technical Communication (TC)", "10:40", "11:40", ""),
    ("Thursday", "Discrete Structures & Theory of Logic (DSTL)", "11:40", "12:25", ""),
    ("Thursday", "Data Structures (DS)", "12:25", "13:10", ""),
    ("Thursday", "Web Designing Workshop", "13:50", "15:10", "Y-310"),
    ("Thursday", "Digital Electronics (DE)", "15:10", "15:50", ""),

    # Friday
    ("Friday", "Aptitude (APT)", "09:40", "10:40", ""),
    ("Friday", "Computer Organization & Architecture (COA)", "10:40", "11:40", ""),
    ("Friday", "Discrete Structures & Theory of Logic (DSTL)", "11:40", "12:25", ""),
    ("Friday", "Data Structures (DS)", "12:25", "13:10", ""),
    ("Friday", "Digital Electronics (DE)", "13:50", "14:30", ""),
    ("Friday", "Technical Communication (TC)", "14:30", "15:10", ""),
    ("Friday", "Data Structures (DS)", "15:10", "15:50", ""),

    # Saturday
    ("Saturday", "Python Programming (PP)", "09:40", "10:40", ""),
    ("Saturday", "Discrete Structures & Theory of Logic (DSTL)", "10:40", "11:40", ""),
    ("Saturday", "Soft Skills (SS)", "11:40", "12:25", ""),
    ("Saturday", "Data Structures (DS)", "12:25", "13:10", ""),
    ("Saturday", "Data Structures Lab", "13:50", "15:10", "S-203"),
    ("Saturday", "Computer Organization & Architecture Lab", "15:10", "15:50", ""),
]

inserted = 0
skipped = 0

with SessionLocal() as db:
    for day, subject, start, end, room in schedule:
        existing = db.scalar(
            select(TimetableEntry).where(
                TimetableEntry.day == day,
                TimetableEntry.subject == subject,
                TimetableEntry.start_time == start,
                TimetableEntry.end_time == end,
                TimetableEntry.room == room,
            )
        )

        if existing:
            skipped += 1
            continue

        db.add(
            TimetableEntry(
                day=day,
                subject=subject,
                start_time=start,
                end_time=end,
                room=room,
            )
        )
        inserted += 1

    db.commit()

print("Timetable import complete!")
print(f"Entries added: {inserted}")
print(f"Existing entries skipped: {skipped}")
print(f"Total scheduled entries: {len(schedule)}")
