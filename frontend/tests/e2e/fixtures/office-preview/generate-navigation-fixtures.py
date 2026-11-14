"""Synthetic documents for keyboard and scroll regressions; no user data."""
from pathlib import Path

from docx import Document
from openpyxl import Workbook

root = Path(__file__).parent
workbook = Workbook()
sheet = workbook.active
sheet.title = "Navigation"
sheet.append(["Start", "Hidden column", "Visible column", "", "Last column"])
sheet.append(["Hidden row"])
sheet.append(["Visible row", "", "Merged cell", "", "After merge"])
sheet.append(["Last row", "", "Below merge"])
sheet.column_dimensions["B"].hidden = True
sheet.row_dimensions[2].hidden = True
sheet.merge_cells("C3:D3")
sheet["A5"] = "Merged across hidden row and column"
sheet.merge_cells("A5:C7")
sheet.row_dimensions[6].hidden = True
sheet["D5"] = "Beside merged range"
sheet["A8"] = "Below merged range"
workbook.create_sheet("Other sheet").append(["Other value"])
sheet["E8"] = "Search target alpha"
workbook["Other sheet"]["A2"] = "Search target beta"
sheet["B8"] = "Search target hidden"
sheet["A501"] = "Search target truncated"
workbook.save(root / "navigation.xlsx")

document = Document()
for page, title in enumerate(("First review page", "Second review page", "Final review page")):
    if page:
        document.add_page_break()
    document.add_heading(title, 1)
    document.add_paragraph("Synthetic document for page navigation and manual scrolling.")
    paragraph = document.add_paragraph()
    paragraph.add_run("Search ").bold = True
    paragraph.add_run("target across styled runs.")
document.save(root / "navigation.docx")
