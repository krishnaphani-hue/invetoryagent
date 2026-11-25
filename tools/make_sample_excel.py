"""Build samples/sample_inventory.xlsx (3 machines) in the upload format.

Run with the backend venv:  backend\\.venv\\Scripts\\python.exe tools\\make_sample_excel.py
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from sample_data import MACHINES, inventory_for

OUT = Path(__file__).resolve().parents[1] / "samples" / "sample_inventory.xlsx"

SHEETS = {
    "machines": ["hostname", "os", "machine_id"],  # machine_id is optional (Windows MachineGuid)
    "installed_software": ["hostname", "name", "version", "publisher"],
    "listening_ports": ["hostname", "protocol", "local_address", "port", "pid", "process_name", "path", "version"],
    "processes": ["hostname", "name", "pid", "path", "version"],
    "services": ["hostname", "name", "display_name", "status", "start_type"],
}


def main() -> None:
    wb = Workbook()
    wb.remove(wb.active)
    sheets = {name: wb.create_sheet(name) for name in SHEETS}
    for name, ws in sheets.items():
        ws.append(SHEETS[name])
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E79")
        ws.freeze_panes = "A2"

    for m in MACHINES:
        inv = inventory_for(m)
        sheets["machines"].append([m["hostname"], m["os"], m["id"]])
        for section in ("installed_software", "listening_ports", "processes", "services"):
            cols = SHEETS[section][1:]
            for row in inv[section]:
                sheets[section].append([m["hostname"], *[row.get(c) for c in cols]])

    for ws in sheets.values():
        for i, col in enumerate(ws.columns, start=1):
            width = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 60)
        # Keep version columns as text so Excel does not turn "8.0" into 8
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if ws.cell(1, c.column).value == "version":
                    c.number_format = "@"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
