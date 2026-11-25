"""Turn an uploaded .xlsx workbook into per-machine InventoryIn payloads.

Workbook layout: one sheet per table, first row = column headers.
  machines            hostname, os, machine_id (optional sheet; machine_id optional)
  installed_software  hostname, name, version, publisher
  listening_ports     hostname, protocol, local_address, port, pid, process_name, path, version
  processes           hostname, name, pid, path, version
  services            hostname, name, display_name, status, start_type
Every data row needs `hostname` (or `machine_id`); rows are grouped into one delivery per machine.
Missing sheets = section not included. Unknown columns are kept in `extra`.
All-or-nothing: if any row is invalid, the whole file is rejected with a list of errors.
"""
from datetime import date, datetime
from io import BytesIO

from openpyxl import load_workbook
from pydantic import ValidationError

from app.models import SECTIONS
from app.schemas import InventoryIn

MACHINE_SHEET = "machines"
KNOWN_SHEETS = {MACHINE_SHEET, *SECTIONS}
KEY_COLUMNS = {"hostname", "machine_id"}


class ExcelError(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__(f"{len(errors)} error(s) in workbook")
        self.errors = errors


def _norm_header(value) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _norm_cell(value):
    """Excel stores '8.0' as a number and dates as datetimes; turn them back into plain values."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# Text columns must stay text even if Excel turned them into numbers (e.g. version 8 -> "8").
_TEXT_COLUMNS = {"version", "name", "publisher", "display_name", "process_name", "path", "hostname", "os",
                 "protocol", "local_address", "status", "start_type"}


def parse_workbook(content: bytes) -> list[InventoryIn]:
    try:
        wb = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # corrupt / not an xlsx
        raise ExcelError([{"sheet": None, "row": None, "error": f"Not a readable .xlsx file: {exc}"}]) from exc

    errors: list[dict] = []
    machines: dict[str, dict] = {}  # key -> payload dict
    found_any = False

    for ws in wb.worksheets:
        sheet = _norm_header(ws.title)
        if sheet not in KNOWN_SHEETS:
            continue
        found_any = True
        rows = ws.iter_rows(values_only=True)
        header_row = next(rows, None)
        if not header_row:
            continue
        headers = [_norm_header(h) for h in header_row]
        if not KEY_COLUMNS & set(headers):
            errors.append({"sheet": ws.title, "row": 1, "error": "missing a 'hostname' (or 'machine_id') column"})
            continue

        for row_no, values in enumerate(rows, start=2):
            record = {}
            for h, v in zip(headers, values):
                if not h:
                    continue
                v = _norm_cell(v)
                if v is not None and h in _TEXT_COLUMNS:
                    v = str(v)
                record[h] = v
            if all(v is None for v in record.values()):
                continue  # blank row

            hostname = record.pop("hostname", None)
            machine_id = record.pop("machine_id", None)
            if not hostname and not machine_id:
                errors.append({"sheet": ws.title, "row": row_no, "error": "hostname is empty"})
                continue
            # Group by hostname (present on every sheet); machine_id is only a fallback key.
            key = str(hostname or machine_id).strip().lower()
            payload = machines.setdefault(key, {"machine": {}, "_rows": {}})
            m = payload["machine"]
            if hostname:
                m.setdefault("hostname", hostname)
            if machine_id:
                m.setdefault("id", str(machine_id))

            if sheet == MACHINE_SHEET:
                for k, v in record.items():
                    if v is not None:
                        m[k] = v
            else:
                payload.setdefault(sheet, []).append(record)
                payload["_rows"].setdefault(sheet, []).append(row_no)

    if not found_any:
        errors.append({"sheet": None, "row": None,
                       "error": f"No known sheets found. Expected some of: {', '.join(sorted(KNOWN_SHEETS))}"})
    if errors:
        raise ExcelError(errors)

    deliveries: list[InventoryIn] = []
    for payload in machines.values():
        row_map = payload.pop("_rows")
        try:
            deliveries.append(InventoryIn.model_validate(payload))
        except ValidationError as exc:
            for err in exc.errors():
                loc = err["loc"]
                sheet, row = None, None
                if loc and loc[0] in SECTIONS and len(loc) > 1 and isinstance(loc[1], int):
                    sheet, row = loc[0], row_map[loc[0]][loc[1]]
                    field = ".".join(str(p) for p in loc[2:])
                elif loc and loc[0] == "machine":
                    sheet, field = MACHINE_SHEET, ".".join(str(p) for p in loc[1:])
                else:
                    field = ".".join(str(p) for p in loc)
                errors.append({"sheet": sheet, "row": row, "error": f"{field}: {err['msg']}".strip(": ")})
    if errors:
        raise ExcelError(errors)
    if not deliveries:
        raise ExcelError([{"sheet": None, "row": None, "error": "The workbook has no data rows"}])
    return deliveries
