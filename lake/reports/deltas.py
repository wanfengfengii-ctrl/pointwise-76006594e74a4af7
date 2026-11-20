from dataclasses import dataclass

from lake.reports.qualification import contribution


@dataclass(frozen=True, slots=True)
class ReportDelta:
    count: int
    liters: int

    def is_zero(self):
        return self.count == 0 and self.liters == 0


def batch_delta(rows, threshold):
    count = 0
    liters = 0
    for row in rows:
        row_count, row_liters = contribution(row.liters, threshold)
        count += row_count
        liters += row_liters
    return ReportDelta(count, liters)


def correction_delta(before_liters, after_liters, threshold):
    before_count, before_total = contribution(before_liters, threshold)
    after_count, after_total = contribution(after_liters, threshold)
    return ReportDelta(after_count - before_count, after_total - before_total)
