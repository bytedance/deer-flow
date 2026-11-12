"""Regenerate workbook.xls with test-only xlwt==1.3.0 (not needed to run tests)."""

import gzip
import io
from datetime import datetime
from pathlib import Path

import xlwt

workbook = xlwt.Workbook()
sheet = workbook.add_sheet("owner's sales")
for column, value in enumerate(["amount", "date", "note", "active"]):
    sheet.write(0, column, value)
date_style = xlwt.easyxf(num_format_str="YYYY-MM-DD")
for row, (amount, date, note, active) in enumerate(
    [(7, datetime(2026, 1, 2), "first", True), (3, datetime(2026, 1, 3), None, False)],
    1,
):
    sheet.write(row, 0, amount)
    sheet.write(row, 1, date, date_style)
    if note is not None:
        sheet.write(row, 2, note)
    sheet.write(row, 3, active)
sheet = workbook.add_sheet("Mixed")
sheet.write(0, 0, "value")
sheet.write(1, 0, 1)
sheet.write(2, 0, "text")
sheet.write(3, 1, "keeps blank value row")
workbook.add_sheet("Empty")
workbook.save(str(Path(__file__).with_name("workbook.xls")))


workbook = xlwt.Workbook()
sheet = workbook.add_sheet("Identifiers")
for column, value in enumerate(["literal", "identifier"]):
    sheet.write(0, column, value)
for row, values in enumerate([("NA", "00123"), ("NULL", "00456"), ("N/A", "00789")], 1):
    for column, value in enumerate(values):
        sheet.write(row, column, value)
workbook.save(str(Path(__file__).with_name("literal-text.xls")))


# Store the larger sampling regression compressed to keep the fixture small.

workbook = xlwt.Workbook()
sheet = workbook.add_sheet("Mixed")
sheet.write(0, 0, "value")
for row in range(10001):
    sheet.write(row + 1, 0, "text" if row == 1001 else 1)
buffer = io.BytesIO()
workbook.save(buffer)
Path(__file__).with_name("sparse-mixed.xls.gz").write_bytes(
    gzip.compress(buffer.getvalue(), mtime=0)
)
