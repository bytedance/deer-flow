"""Synthetic chart-only drawing that ExcelJS 4.4 cannot reconcile."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.worksheet.table import Table, TableStyleInfo

workbook = Workbook()
summary = workbook.active
summary.title = "Summary"
for row in (("Team", "Tasks"), ("Design", 8), ("Engineering", 12)):
    summary.append(row)
table = Table(displayName="Teams", ref="A1:B3")
table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
summary.add_table(table)
chart = BarChart()
chart.title = "Tasks by team"
chart.add_data(Reference(summary, min_col=2, min_row=1, max_row=3), titles_from_data=True)
chart.set_categories(Reference(summary, min_col=1, min_row=2, max_row=3))
summary.add_chart(chart, "D2")
detail = workbook.create_sheet("Design")
detail.append(("Design review", "Ready"))
detail["A2"] = "Documentation"
detail["A2"].hyperlink = "https://example.com/design"
workbook.save(Path(__file__).with_name("chart-only.xlsx"))
