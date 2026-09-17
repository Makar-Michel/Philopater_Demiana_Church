import asyncio
import json
import os
import sqlite3
import shutil
import base64
import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import flet as ft

# =========================================================
# PATHS & DIRECTORIES
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
DB_FILE = os.path.join(BASE_DIR, "church.db")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")

for folder in [ASSETS_DIR, UPLOADS_DIR, BACKUPS_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)

def get_icon_path():
    for icon_name in ("icon.ico", "icon.png"):
        icon_path = os.path.join(ASSETS_DIR, icon_name)
        if os.path.exists(icon_path):
            return icon_path
    return ""

def make_upload_photo_name(source_name=""):
    ext = os.path.splitext(source_name or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        ext = ".jpg"
    return f"confessor_{os.urandom(4).hex()}{ext}"

def file_to_base64(file_path):
    if not file_path or not os.path.exists(file_path):
        return ""
    try:
        ext = os.path.splitext(file_path)[1].lower().replace(".", "")
        if ext == "jpg":
            ext = "jpeg"
        with open(file_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            return f"data:image/{ext};base64,{encoded_string}"
    except Exception as e:
        print(f"Error encoding image: {e}")
        return ""

def resolve_image_path(filename):
    if not filename:
        return ""

    name_only = os.path.basename(filename)
    candidates = [
        os.path.join(UPLOADS_DIR, name_only),
        os.path.join(ASSETS_DIR, name_only),
        os.path.join(ASSETS_DIR, "people", name_only),
        os.path.join(BASE_DIR, filename),
        os.path.join(BASE_DIR, name_only),
        filename,
    ]

    for path in candidates:
        if os.path.exists(path):
            return file_to_base64(path)
    return ""

# =========================================================
# DATABASE & BACKUP LOGIC
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS confessors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            birth_date TEXT,
            phone TEXT,
            address TEXT,
            last_confession TEXT,
            has_family INTEGER DEFAULT 0,
            family_json TEXT,
            notes TEXT,
            photo TEXT
        )
        """
    )
    conn.commit()
    conn.close()

def auto_backup():
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_file = os.path.join(BACKUPS_DIR, f"auto_backup_{timestamp}.db")
        shutil.copy2(DB_FILE, backup_file)
        return backup_file
    except Exception as e:
        print(f"Auto backup error: {e}")
        return None

def save_confessor(name, birth_date, phone, address, last_confession, has_family, family_members, notes, photo, confessor_id=None):
    conn = get_db()
    family_json = json.dumps(family_members, ensure_ascii=False)
    clean_photo_name = os.path.basename(photo) if photo else ""
    
    if confessor_id:
        conn.execute(
            """
            UPDATE confessors 
            SET name=?, birth_date=?, phone=?, address=?, last_confession=?, has_family=?, family_json=?, notes=?, photo=?
            WHERE id=?
            """,
            (name, birth_date, phone, address, last_confession, 1 if has_family else 0, family_json, notes, clean_photo_name, confessor_id)
        )
    else:
        conn.execute(
            """
            INSERT INTO confessors (name, birth_date, phone, address, last_confession, has_family, family_json, notes, photo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, birth_date, phone, address, last_confession, 1 if has_family else 0, family_json, notes, clean_photo_name)
        )

    conn.commit()
    conn.close()
    auto_backup()

def delete_confessor_db(confessor_id):
    conn = get_db()
    conn.execute("DELETE FROM confessors WHERE id = ?", (confessor_id,))
    conn.commit()
    conn.close()
    auto_backup()

def get_confessors(search_text=""):
    conn = get_db()
    text = (search_text or "").strip()
    if text:
        rows = conn.execute("SELECT * FROM confessors WHERE name LIKE ? ORDER BY name", (f"%{text}%",)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM confessors ORDER BY name").fetchall()
    conn.close()
    return rows

def get_confessor(confessor_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM confessors WHERE id = ?", (confessor_id,)).fetchone()
    conn.close()
    return row

def normalize_header(value):
    text = str(value or "").strip().lower()
    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ة": "ه",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[\u064b-\u065f\u0670ـ]", "", text)
    text = re.sub(r"[^0-9a-z\u0600-\u06ff]+", "", text)
    return text

FIELD_ALIASES = {
    "name": ["الاسم", "اسم", "اسمالمعترف", "الاسمالكامل", "name", "fullname"],
    "birth_date": ["تاريخالميلاد", "الميلاد", "السن", "العمر", "birthdate", "dateofbirth", "age"],
    "phone": ["الهاتف", "رقمالهاتف", "الموبايل", "رقمالموبايل", "التليفون", "رقمالتليفون", "phone", "mobile"],
    "address": ["العنوان", "عنوان", "address"],
    "last_confession": ["اخرالاعتراف", "اخراعتراف", "اخرمرهاعترف", "اخرمره", "lastconfession"],
    "notes": ["ملاحظات", "ملاحظه", "notes", "note"],
}

def get_row_value(row, field_name):
    normalized_row = {normalize_header(k): str(v or "").strip() for k, v in row.items()}
    for alias in FIELD_ALIASES[field_name]:
        value = normalized_row.get(normalize_header(alias), "")
        if value:
            return value
    return ""

def clean_excel_value(value):
    text = str(value or "").strip()
    if re.fullmatch(r"0\d+", text):
        return text
    if re.fullmatch(r"-?\d+(\.\d+)?([eE][+-]?\d+)?", text):
        try:
            number = Decimal(text)
            if number == number.to_integral_value():
                return format(number.quantize(Decimal(1)), "f")
        except (InvalidOperation, ValueError):
            pass
    if re.fullmatch(r"-?\d+\.0", text):
        return text[:-2]
    return text

def excel_serial_to_date(value):
    try:
        serial = float(value)
        if serial <= 0:
            return clean_excel_value(value)
        base = datetime(1899, 12, 30)
        return (base + timedelta(days=serial)).strftime("%d/%m/%Y")
    except Exception:
        return clean_excel_value(value)

def read_text_sheet(raw_data):
    content_str = ""
    for enc in ["utf-8-sig", "utf-8", "cp1256", "windows-1256", "iso-8859-1"]:
        try:
            content_str = raw_data.decode(enc)
            break
        except (UnicodeDecodeError, TypeError):
            continue

    if not content_str:
        raise ValueError("فشل في قراءة ترميز الملف. لو الملف CSV احفظه بترميز UTF-8.")

    sample = content_str[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except Exception:
        first_line = content_str.splitlines()[0] if content_str.splitlines() else ""
        delimiter = "\t" if "\t" in first_line else (";" if ";" in first_line and "," not in first_line else ",")

    reader = csv.DictReader(io.StringIO(content_str), delimiter=delimiter)
    return [{str(k).strip(): clean_excel_value(v) for k, v in row.items() if k} for row in reader]

def xml_namespace(root):
    if root.tag.startswith("{"):
        return {"x": root.tag[1:].split("}")[0]}
    return {}

def get_xlsx_shared_strings(zip_file):
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []
    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    ns = xml_namespace(root)
    strings = []
    for item in root.findall(".//x:si", ns):
        parts = []
        for text_node in item.findall(".//x:t", ns):
            parts.append(text_node.text or "")
        strings.append("".join(parts))
    return strings

def get_xlsx_date_styles(zip_file):
    if "xl/styles.xml" not in zip_file.namelist():
        return set()

    root = ET.fromstring(zip_file.read("xl/styles.xml"))
    ns = xml_namespace(root)
    custom_date_ids = set()
    standard_date_ids = {14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 30, 36, 45, 46, 47, 50, 57}

    for num_fmt in root.findall(".//x:numFmt", ns):
        fmt_id = int(num_fmt.attrib.get("numFmtId", "0"))
        fmt_code = num_fmt.attrib.get("formatCode", "").lower()
        if any(ch in fmt_code for ch in ["d", "m", "y", "h", "s"]):
            custom_date_ids.add(fmt_id)

    date_styles = set()
    cell_xfs = root.find(".//x:cellXfs", ns)
    if cell_xfs is not None:
        for index, xf in enumerate(cell_xfs.findall("x:xf", ns)):
            fmt_id = int(xf.attrib.get("numFmtId", "0"))
            if fmt_id in standard_date_ids or fmt_id in custom_date_ids:
                date_styles.add(index)
    return date_styles

def get_first_xlsx_sheet_path(zip_file):
    names = set(zip_file.namelist())
    if "xl/workbook.xml" not in names:
        return "xl/worksheets/sheet1.xml"

    workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
    ns = xml_namespace(workbook)
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    first_sheet = workbook.find(".//x:sheet", ns)
    if first_sheet is None:
        return "xl/worksheets/sheet1.xml"

    rel_id = first_sheet.attrib.get(f"{{{rel_ns}}}id")
    if not rel_id or "xl/_rels/workbook.xml.rels" not in names:
        return "xl/worksheets/sheet1.xml"

    rels = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    for rel in rels:
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target", "worksheets/sheet1.xml")
            if target.startswith("/"):
                return target.lstrip("/")
            return "xl/" + target.lstrip("/")
    return "xl/worksheets/sheet1.xml"

def column_index_from_ref(cell_ref):
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch.upper()) - ord("A") + 1)
    return max(index - 1, 0)

def read_xlsx_sheet(raw_data):
    with zipfile.ZipFile(io.BytesIO(raw_data)) as zip_file:
        sheet_path = get_first_xlsx_sheet_path(zip_file)
        if sheet_path not in zip_file.namelist():
            raise ValueError("لم أجد أول شيت داخل ملف Excel.")

        shared_strings = get_xlsx_shared_strings(zip_file)
        date_styles = get_xlsx_date_styles(zip_file)
        sheet = ET.fromstring(zip_file.read(sheet_path))
        ns = xml_namespace(sheet)
        table_rows = []

        for row_node in sheet.findall(".//x:sheetData/x:row", ns):
            values = []
            for cell in row_node.findall("x:c", ns):
                col_index = column_index_from_ref(cell.attrib.get("r", "A1"))
                while len(values) <= col_index:
                    values.append("")

                cell_type = cell.attrib.get("t", "")
                style_index = int(cell.attrib.get("s", "0") or "0")
                value_node = cell.find("x:v", ns)

                if cell_type == "s" and value_node is not None:
                    idx = int(value_node.text or "0")
                    value = shared_strings[idx] if idx < len(shared_strings) else ""
                elif cell_type == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(".//x:t", ns))
                elif value_node is not None:
                    value = value_node.text or ""
                    if style_index in date_styles:
                        value = excel_serial_to_date(value)
                    else:
                        value = clean_excel_value(value)
                else:
                    value = ""

                values[col_index] = value

            if any(str(v).strip() for v in values):
                table_rows.append(values)

    if not table_rows:
        return []

    headers = [str(v).strip() for v in table_rows[0]]
    records = []
    for values in table_rows[1:]:
        record = {}
        for idx, header in enumerate(headers):
            if header:
                record[header] = clean_excel_value(values[idx] if idx < len(values) else "")
        records.append(record)
    return records

def insert_sheet_rows_to_db(rows):
    count = 0
    skipped_duplicates = 0
    conn = get_db()
    try:
        for row in rows:
            name = get_row_value(row, "name")
            if not name:
                continue

            birth_date = get_row_value(row, "birth_date")
            phone = get_row_value(row, "phone")
            address = get_row_value(row, "address")
            last_confession = get_row_value(row, "last_confession")
            notes = get_row_value(row, "notes")

            if phone:
                duplicate = conn.execute(
                    "SELECT id FROM confessors WHERE name = ? AND phone = ? LIMIT 1",
                    (name, phone),
                ).fetchone()
                if duplicate:
                    skipped_duplicates += 1
                    continue

            conn.execute(
                """
                INSERT INTO confessors (name, birth_date, phone, address, last_confession, has_family, family_json, notes, photo)
                VALUES (?, ?, ?, ?, ?, 0, '[]', ?, '')
                """,
                (name, birth_date, phone, address, last_confession, notes),
            )
            count += 1

        conn.commit()
    finally:
        conn.close()

    if count:
        auto_backup()
    return count, skipped_duplicates

def import_sheet_to_db(file_stream_or_path, file_name=""):
    """استيراد CSV/TSV/XLSX إلى جدول المعترفين."""
    try:
        if isinstance(file_stream_or_path, bytes):
            raw_data = file_stream_or_path
        elif isinstance(file_stream_or_path, str) and os.path.exists(file_stream_or_path):
            with open(file_stream_or_path, "rb") as f:
                raw_data = f.read()
            if not file_name:
                file_name = os.path.basename(file_stream_or_path)
        else:
            return False, "تعذر الوصول للملف أو قراءة بياناته"

        ext = os.path.splitext(file_name or "")[1].lower()
        is_xlsx = ext == ".xlsx" or raw_data[:2] == b"PK"
        rows = read_xlsx_sheet(raw_data) if is_xlsx else read_text_sheet(raw_data)

        if not rows:
            return False, "الشيت فارغ أو لا يحتوي على صفوف بيانات"

        count, skipped = insert_sheet_rows_to_db(rows)
        if count == 0:
            return False, "لم أجد عمود الاسم. خلي أول صف يحتوي على: الاسم، رقم الهاتف، العنوان، تاريخ الميلاد، آخر اعتراف، ملاحظات"

        extra = f" وتم تجاهل {skipped} مكرر" if skipped else ""
        return True, f"تم استيراد {count} معترف بنجاح{extra}!"
    except zipfile.BadZipFile:
        return False, "ملف Excel غير صالح. اختر ملف .xlsx أو احفظ الشيت CSV."
    except Exception as e:
        return False, f"خطأ أثناء الاستيراد: {str(e)}"

def excel_column_name(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name

def xml_escape(value):
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

def xlsx_inline_cell(row_index, col_index, value):
    cell_ref = f"{excel_column_name(col_index)}{row_index}"
    safe_value = xml_escape(value)
    return f'<c r="{cell_ref}" t="inlineStr"><is><t>{safe_value}</t></is></c>'

def build_confessors_xlsx_bytes():
    rows = get_confessors("")
    headers = ["الاسم", "تاريخ الميلاد", "رقم الهاتف", "العنوان", "آخر اعتراف", "لديه أسرة", "أفراد الأسرة", "ملاحظات", "الصورة"]
    sheet_rows = []
    sheet_rows.append(headers)

    for row in rows:
        try:
            family_members = json.loads(row["family_json"] or "[]")
        except Exception:
            family_members = []
        family_text = "؛ ".join(
            f"{member.get('name', '')} ({member.get('relation', '')})".strip()
            for member in family_members
            if member.get("name")
        )
        sheet_rows.append([
            row["name"] or "",
            row["birth_date"] or "",
            row["phone"] or "",
            row["address"] or "",
            row["last_confession"] or "",
            "نعم" if row["has_family"] else "لا",
            family_text,
            row["notes"] or "",
            row["photo"] or "",
        ])

    worksheet_rows = []
    for row_index, values in enumerate(sheet_rows, start=1):
        cells = "".join(xlsx_inline_cell(row_index, col_index, value) for col_index, value in enumerate(values, start=1))
        worksheet_rows.append(f'<row r="{row_index}">{cells}</row>')

    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheetViews><sheetView rightToLeft="1" workbookViewId="0"/></sheetViews>
<cols>
<col min="1" max="1" width="28" customWidth="1"/>
<col min="2" max="5" width="18" customWidth="1"/>
<col min="6" max="6" width="12" customWidth="1"/>
<col min="7" max="8" width="35" customWidth="1"/>
<col min="9" max="9" width="24" customWidth="1"/>
</cols>
<sheetData>{''.join(worksheet_rows)}</sheetData>
</worksheet>'''

    workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="المعترفين" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''

    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''

    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''

    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>'''

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("[Content_Types].xml", content_types)
        zip_file.writestr("_rels/.rels", root_rels)
        zip_file.writestr("xl/workbook.xml", workbook_xml)
        zip_file.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zip_file.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue(), len(rows)

# =========================================================
# MAIN APPLICATION
# =========================================================

def main(page: ft.Page):
    init_db()

    page.title = "راعي الرعاة"
    page.padding = 0
    page.spacing = 0
    page.bgcolor = "#000000"
    page.rtl = True
    page.assets_dir = ASSETS_DIR
    
    icon_path = get_icon_path()
    if icon_path:
        try:
            page.window.icon = icon_path
        except Exception as ex:
            print(f"Window icon error: {ex}")

    current_photo = {"value": ""}
    family_inputs = []

    def show_snack(msg):
        snack = ft.SnackBar(content=ft.Text(msg, text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD, color="#FFFFFF"))
        page.overlay.append(snack)
        snack.open = True
        page.update()

    def church_background(content):
        return ft.Stack(
            expand=True,
            controls=[
                ft.Image(
                    src="church_main.webp",
                    width=float("inf"),
                    height=float("inf"),
                    fit=ft.BoxFit.COVER,
                ),
                ft.Container(expand=True, bgcolor="#00000055"),
                content,
            ],
        )

    excel_export_picker = ft.FilePicker()
    page.services.append(excel_export_picker)

    async def export_excel_backup_action(e):
        try:
            excel_bytes, row_count = build_confessors_xlsx_bytes()
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_name = f"confessors_backup_{timestamp}.xlsx"
            local_backup_path = os.path.join(BACKUPS_DIR, backup_name)

            with open(local_backup_path, "wb") as backup_file:
                backup_file.write(excel_bytes)

            saved_path = await excel_export_picker.save_file(
                dialog_title="احفظ ملف Excel",
                file_name=backup_name,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["xlsx"],
                src_bytes=excel_bytes,
            )

            if saved_path:
                show_snack(f"تم تصدير {row_count} معترف إلى Excel:\n{backup_name}")
            else:
                show_snack(f"تم حفظ ملف Excel في backups:\n{backup_name}")
        except Exception as ex:
            show_snack(f"خطأ: {ex}")

    last_import_key = {"value": ""}

    def import_selected_sheet_file(selected_file):
        try:
            file_bytes = getattr(selected_file, "bytes", None)
            file_path = getattr(selected_file, "path", None)
            file_name = getattr(selected_file, "name", None) or os.path.basename(file_path or "")
            file_key = f"{file_name}:{getattr(selected_file, 'size', '')}:{file_path or ''}"
            if file_key == last_import_key["value"]:
                return
            last_import_key["value"] = file_key

            if file_bytes:
                success, msg = import_sheet_to_db(file_bytes, file_name)
            elif file_path and os.path.exists(file_path):
                success, msg = import_sheet_to_db(file_path, file_name)
            else:
                show_snack("تعذر قراءة بيانات الملف المختار")
                return

            show_snack(msg)
            if success:
                show_confessions()
        except Exception as ex:
            show_snack(f"خطأ غير متوقع: {ex}")

    def on_excel_picked(e: ft.FilePickerResultEvent):
        if e.files and len(e.files) > 0:
            import_selected_sheet_file(e.files[0])
        else:
            show_snack("تم إلغاء اختيار الملف")

    excel_picker = ft.FilePicker(on_result=on_excel_picked)
    page.services.append(excel_picker)

    async def import_excel_click(e):
        selected_files = await excel_picker.pick_files(
            allow_multiple=False,
            dialog_title="اختر ملف الشيت",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["xlsx", "csv", "tsv"],
            with_data=True,
        )
        if selected_files and len(selected_files) > 0:
            import_selected_sheet_file(selected_files[0])

    def show_home(e=None):
        page.controls.clear()

        logo_image = ft.Image(
            src="icon.png",
            width=80,
            height=80,
            fit=ft.BoxFit.CONTAIN
        )

        title = ft.Text("تطبيق راعي الرعاة", size=26, weight=ft.FontWeight.BOLD, color="#FFFFFF", text_align=ft.TextAlign.CENTER)
        subtitle = ft.Text("كنيسة الشهيد العظيم أبي سيفين والقديسة دميانة", size=15, weight=ft.FontWeight.BOLD, color="#EEEEEE", text_align=ft.TextAlign.CENTER)

        confession_card = ft.Container(
            width=340,
            padding=22,
            border_radius=22,
            bgcolor="#121212EE",
            border=ft.Border.all(1.5, "#FFFFFF88"),
            ink=True,
            on_click=lambda e: show_confessions(),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
                controls=[
                    ft.Container(
                        width=55,
                        height=55,
                        border_radius=28,
                        bgcolor="#FFFFFF20",
                        alignment=ft.Alignment(0, 0),
                        content=ft.Text("✝", size=28, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                    ),
                    ft.Text("الاعترافات", size=22, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                    ft.Text("إدارة بيانات المعترفين", size=13, weight=ft.FontWeight.BOLD, color="#DDDDDD"),
                ],
            ),
        )

        backup_btn = ft.Button("Backup Sheet", icon=ft.Icons.DOWNLOAD, on_click=export_excel_backup_action)
        excel_btn = ft.Button("Upload Sheet", icon=ft.Icons.TABLE_CHART, on_click=import_excel_click)

        main_card = ft.Container(
            width=480,
            padding=25,
            border_radius=28,
            bgcolor="#121212EE",
            border=ft.Border.all(2, "#FFFFFF"),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
                controls=[
                    logo_image,
                    title, 
                    subtitle, 
                    ft.Container(height=5), 
                    confession_card,
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, wrap=True, spacing=8, controls=[backup_btn, excel_btn])
                ],
            ),
        )

        content = ft.Container(expand=True, alignment=ft.Alignment(0, 0), padding=20, content=main_card)
        page.add(church_background(content))
        page.update()

    def show_confessions(search_value=""):
        page.controls.clear()

        search_field = ft.TextField(
            label="بحث عن معترف",
            hint_text="اكتب الاسم",
            expand=True,
            prefix_icon=ft.Icons.SEARCH,
            filled=True,
            bgcolor="#121212",
            color="#FFFFFF",
            label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD),
            border=ft.OutlineInputBorder(border_radius=14, side=ft.BorderSide(color="#FFFFFF")),
            value=search_value,
        )

        list_column = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

        def do_search(e=None):
            refresh_list()

        search_field.on_submit = do_search

        def refresh_list():
            list_column.controls.clear()
            rows = get_confessors(search_field.value or "")

            if not rows:
                list_column.controls.append(
                    ft.Container(
                        padding=25,
                        alignment=ft.Alignment(0, 0),
                        bgcolor="#121212",
                        border_radius=18,
                        border=ft.Border.all(1.5, "#FFFFFF"),
                        content=ft.Text("لا يوجد معترفين حتى الآن", size=16, weight=ft.FontWeight.BOLD, color="#FFFFFF", text_align=ft.TextAlign.CENTER),
                    )
                )
            else:
                for row in rows:
                    photo_b64 = resolve_image_path(row["photo"])
                    if photo_b64:
                        image_control = ft.Image(src=photo_b64, width=58, height=58, fit=ft.BoxFit.COVER, border_radius=29)
                    else:
                        image_control = ft.Container(
                            width=58,
                            height=58,
                            border_radius=29,
                            bgcolor="#FFFFFF20",
                            alignment=ft.Alignment(0, 0),
                            content=ft.Icon(ft.Icons.PERSON, size=28, color="#FFFFFF"),
                        )

                    family_text = "لديه أسرة" if row["has_family"] else "بدون أسرة"

                    card = ft.Container(
                        padding=14,
                        border_radius=18,
                        bgcolor="#121212",
                        border=ft.Border.all(1.5, "#FFFFFF"),
                        ink=True,
                        on_click=lambda e, rid=row["id"]: show_profile(rid),
                        content=ft.Row(
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                image_control,
                                ft.Column(
                                    expand=True,
                                    spacing=4,
                                    controls=[
                                        ft.Text(row["name"], size=18, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                                        ft.Text(f"الهاتف: {row['phone'] or 'لا يوجد'}", size=13, weight=ft.FontWeight.BOLD, color="#EEEEEE"),
                                        ft.Text(family_text, size=12, weight=ft.FontWeight.BOLD, color="#CCCCCC"),
                                    ],
                                ),
                                ft.Icon(ft.Icons.ARROW_BACK_IOS_NEW, size=18, color="#FFFFFF"),
                            ],
                        ),
                    )
                    list_column.controls.append(card)
            page.update()

        add_button = ft.Button("إنشاء معترف جديد", icon=ft.Icons.PERSON_ADD_ALT_1, on_click=lambda e: show_form_confessor())
        search_button = ft.Button("بحث", icon=ft.Icons.SEARCH, on_click=do_search)
        back_button = ft.Button("رجوع", icon=ft.Icons.ARROW_BACK, on_click=show_home)

        header_title = ft.Container(
            padding=ft.Padding(15, 8, 15, 8),
            bgcolor="#121212",
            border_radius=12,
            border=ft.Border.all(1.5, "#FFFFFF"),
            content=ft.Text("الاعترافات", size=22, weight=ft.FontWeight.BOLD, color="#FFFFFF")
        )

        confessions_card = ft.Container(
            width=500,
            padding=20,
            border_radius=24,
            bgcolor="#121212EE",
            border=ft.Border.all(2, "#FFFFFF"),
            content=ft.Column(
                expand=True,
                spacing=12,
                controls=[
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[header_title, back_button]),
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[search_field, search_button]),
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[add_button]),
                    ft.Divider(color="#FFFFFF88", height=10),
                    list_column,
                ],
            )
        )

        content = ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            padding=20,
            content=confessions_card
        )

        page.add(church_background(content))
        refresh_list()

    def add_family_member_ui(family_column, name_val="", rel_val=""):
        member_name = ft.TextField(
            label="اسم فرد الأسرة", 
            expand=True, 
            filled=True,
            bgcolor="#121212", 
            color="#FFFFFF", 
            label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD), 
            border=ft.OutlineInputBorder(border_radius=12, side=ft.BorderSide(color="#FFFFFF")), 
            value=name_val
        )
        relation = ft.TextField(
            label="صلة القرابة", 
            width=140, 
            filled=True,
            bgcolor="#121212", 
            color="#FFFFFF", 
            label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD), 
            border=ft.OutlineInputBorder(border_radius=12, side=ft.BorderSide(color="#FFFFFF")), 
            value=rel_val
        )

        item_ref = {"name_field": member_name, "rel_field": relation}
        family_inputs.append(item_ref)

        def delete_member(e):
            family_column.controls.remove(member_container)
            if item_ref in family_inputs:
                family_inputs.remove(item_ref)
            page.update()

        member_container = ft.Container(
            padding=8,
            border_radius=14,
            bgcolor="#121212",
            border=ft.Border.all(1, "#FFFFFF"),
            content=ft.Row(wrap=True, controls=[member_name, relation, ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#FFFFFF", on_click=delete_member)]),
        )

        family_column.controls.append(member_container)
        page.update()

    def show_form_confessor(edit_id=None):
        page.controls.clear()
        family_inputs.clear()

        edit_data = get_confessor(edit_id) if edit_id else None
        current_photo["value"] = edit_data["photo"] if edit_data else ""

        def create_styled_textfield(label, hint="", multiline=False, min_lines=1, max_lines=1, keyboard_type=ft.KeyboardType.TEXT, value=""):
            return ft.TextField(
                label=label,
                hint_text=hint,
                width=380,
                multiline=multiline,
                min_lines=min_lines,
                max_lines=max_lines,
                keyboard_type=keyboard_type,
                filled=True,
                bgcolor="#121212",
                color="#FFFFFF",
                hint_style=ft.TextStyle(color="#AAAAAA"),
                label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD),
                border=ft.OutlineInputBorder(border_radius=14, side=ft.BorderSide(color="#FFFFFF")),
                value=value
            )

        name_field = create_styled_textfield("الاسم *", value=edit_data["name"] if edit_data else "")
        birth_field = create_styled_textfield("تاريخ الميلاد / السن", hint="15/08/1985", value=edit_data["birth_date"] if edit_data else "")
        phone_field = create_styled_textfield("رقم الهاتف", keyboard_type=ft.KeyboardType.PHONE, value=edit_data["phone"] if edit_data else "")
        address_field = create_styled_textfield("العنوان", multiline=True, min_lines=2, max_lines=4, value=edit_data["address"] if edit_data else "")
        last_confession_field = create_styled_textfield("آخر مرة اعترف إمتى؟", hint="01/09/2026", value=edit_data["last_confession"] if edit_data else "")
        notes_field = create_styled_textfield("ملاحظات", multiline=True, min_lines=3, max_lines=6, value=edit_data["notes"] if edit_data else "")

        initial_photo_b64 = resolve_image_path(current_photo["value"])
        
        photo_preview = ft.Image(
            src=initial_photo_b64 if initial_photo_b64 else "", 
            width=120, 
            height=120, 
            fit=ft.BoxFit.COVER, 
            border_radius=60, 
            visible=bool(initial_photo_b64)
        )
        photo_placeholder = ft.Container(
            width=120, 
            height=120, 
            border_radius=60, 
            bgcolor="#121212", 
            border=ft.Border.all(2, "#FFFFFF"), 
            alignment=ft.Alignment(0, 0), 
            visible=not bool(initial_photo_b64), 
            content=ft.Icon(ft.Icons.PERSON, size=48, color="#FFFFFF")
        )

        def save_picked_photo(selected_file):
            file_path = getattr(selected_file, "path", None)
            file_name = getattr(selected_file, "name", None) or os.path.basename(file_path or "photo.jpg")

            try:
                target_name = make_upload_photo_name(file_name)
                target_path = os.path.join(UPLOADS_DIR, target_name)
                file_bytes = getattr(selected_file, "bytes", None)

                if file_bytes:
                    with open(target_path, "wb") as image_file:
                        image_file.write(file_bytes)
                elif file_path and os.path.exists(file_path):
                    shutil.copy2(file_path, target_path)
                else:
                    show_snack("لم يتم قراءة الصورة بشكل صحيح")
                    return

                current_photo["value"] = target_name
                photo_preview.src = file_to_base64(target_path)
                photo_preview.visible = True
                photo_placeholder.visible = False
                page.update()
                show_snack("تم اختيار الصورة بنجاح!")
            except Exception as ex:
                show_snack(f"خطأ في حفظ الصورة: {ex}")

        def on_photo_picked(e: ft.FilePickerResultEvent):
            if e.files and len(e.files) > 0:
                save_picked_photo(e.files[0])

        photo_picker = ft.FilePicker(on_result=on_photo_picked)
        page.services.append(photo_picker)

        async def pick_photo_click(e):
            await photo_picker.pick_files(
                allow_multiple=False, 
                file_type=ft.FilePickerFileType.IMAGE,
                with_data=True,
            )

        photo_button = ft.Button("إضافة صورة", icon=ft.Icons.CAMERA_ALT_OUTLINED, on_click=pick_photo_click)
        photo_area = ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10, controls=[photo_placeholder, photo_preview, photo_button])

        family_switch = ft.Switch(label="لديه أسرة", value=bool(edit_data["has_family"]) if edit_data else False)
        family_column = ft.Column(spacing=8, visible=family_switch.value)
        add_family_button = ft.Button("إضافة فرد للأسرة", icon=ft.Icons.PERSON_ADD_ALT_1, visible=family_switch.value, on_click=lambda e: add_family_member_ui(family_column))

        def family_changed(e):
            family_column.visible = family_switch.value
            add_family_button.visible = family_switch.value
            page.update()

        family_switch.on_change = family_changed
        family_section = ft.Container(width=380, padding=15, border_radius=18, bgcolor="#121212", border=ft.Border.all(1.5, "#FFFFFF"), content=ft.Column(spacing=10, controls=[family_switch, family_column, add_family_button]))

        if edit_data and edit_data["has_family"]:
            try:
                members = json.loads(edit_data["family_json"] or "[]")
                for m in members:
                    add_family_member_ui(family_column, m.get("name", ""), m.get("relation", ""))
            except Exception:
                pass

        def save_person(e):
            name = (name_field.value or "").strip()
            if not name:
                show_snack("اكتب اسم المعترف أولًا")
                return

            parsed_family = []
            if family_switch.value:
                for item in family_inputs:
                    m_name = (item["name_field"].value or "").strip()
                    m_rel = (item["rel_field"].value or "").strip()
                    if m_name:
                        parsed_family.append({"name": m_name, "relation": m_rel})

            save_confessor(
                name=name,
                birth_date=birth_field.value or "",
                phone=phone_field.value or "",
                address=address_field.value or "",
                last_confession=last_confession_field.value or "",
                has_family=family_switch.value,
                family_members=parsed_family,
                notes=notes_field.value or "",
                photo=current_photo["value"],
                confessor_id=edit_id,
            )

            show_snack("تم حفظ البيانات بنجاح")
            show_confessions()

        back_button = ft.Button("رجوع", icon=ft.Icons.ARROW_BACK, on_click=lambda e: show_confessions())
        save_button = ft.Button("حفظ المعترف", icon=ft.Icons.SAVE_OUTLINED, on_click=save_person)

        form_title = ft.Container(
            padding=ft.Padding(15, 8, 15, 8),
            bgcolor="#121212",
            border_radius=12,
            border=ft.Border.all(1.5, "#FFFFFF"),
            content=ft.Text("تعديل / إنشاء معترف", size=22, weight=ft.FontWeight.BOLD, color="#FFFFFF")
        )

        form_card = ft.Container(
            width=480,
            padding=20,
            border_radius=24,
            bgcolor="#121212EE",
            border=ft.Border.all(2, "#FFFFFF"),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=14,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[form_title, back_button]),
                    photo_area,
                    name_field,
                    birth_field,
                    phone_field,
                    address_field,
                    last_confession_field,
                    family_section,
                    notes_field,
                    save_button,
                ],
            )
        )

        page.add(church_background(ft.Container(expand=True, alignment=ft.Alignment(0, 0), padding=20, content=form_card)))
        page.update()

    def show_profile(confessor_id):
        row = get_confessor(confessor_id)
        if not row:
            show_snack("لم يتم العثور على البيانات")
            return

        page.controls.clear()

        photo_b64 = resolve_image_path(row["photo"])
        if photo_b64:
            profile_image = ft.Image(src=photo_b64, width=140, height=140, fit=ft.BoxFit.COVER, border_radius=70)
        else:
            profile_image = ft.Container(
                width=140, 
                height=140, 
                border_radius=70, 
                bgcolor="#121212", 
                border=ft.Border.all(2, "#FFFFFF"),
                alignment=ft.Alignment(0, 0), 
                content=ft.Icon(ft.Icons.PERSON, size=60, color="#FFFFFF")
            )

        def info_row(icon, title, value):
            return ft.Container(
                padding=14,
                border_radius=14,
                bgcolor="#121212",
                border=ft.Border.all(1.5, "#FFFFFF"),
                content=ft.Row(
                    controls=[
                        ft.Icon(icon, size=24, color="#FFFFFF"),
                        ft.Column(
                            expand=True,
                            spacing=4,
                            controls=[
                                ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color="#DDDDDD"),
                                ft.Text(value or "غير مسجل", size=17, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                            ],
                        ),
                    ],
                ),
            )

        family_controls = [ft.Text("الأسرة", size=20, weight=ft.FontWeight.BOLD, color="#FFFFFF")]
        if row["has_family"]:
            try:
                family_members = json.loads(row["family_json"] or "[]")
            except Exception:
                family_members = []

            if family_members:
                for member in family_members:
                    family_controls.append(
                        ft.Container(
                            padding=10,
                            border_radius=12,
                            bgcolor="#121212",
                            border=ft.Border.all(1, "#FFFFFF"),
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.PERSON, size=22, color="#FFFFFF"),
                                    ft.Column(
                                        expand=True, 
                                        spacing=2, 
                                        controls=[
                                            ft.Text(member.get("name", ""), size=16, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                                            ft.Text(member.get("relation", "") or "صلة القرابة غير محددة", size=13, weight=ft.FontWeight.BOLD, color="#DDDDDD"),
                                        ]
                                    ),
                                ]
                            ),
                        )
                    )
            else:
                family_controls.append(ft.Text("لم يتم إضافة أفراد للأسرة", size=14, weight=ft.FontWeight.BOLD, color="#CCCCCC"))
        else:
            family_controls.append(ft.Text("ليس لديه أسرة مسجلة", size=14, weight=ft.FontWeight.BOLD, color="#CCCCCC"))

        def confirm_delete(e):
            delete_confessor_db(confessor_id)
            show_snack("تم حذف المعترف بنجاح")
            show_confessions()

        edit_btn = ft.Button("تعديل البيانات", icon=ft.Icons.EDIT, on_click=lambda e: show_form_confessor(confessor_id))
        delete_btn = ft.Button("حذف المعترف", icon=ft.Icons.DELETE, bgcolor="#880000", color="#FFFFFF", on_click=confirm_delete)
        back_button = ft.Button("رجوع", icon=ft.Icons.ARROW_BACK, on_click=lambda e: show_confessions())

        profile_title = ft.Container(
            padding=ft.Padding(15, 8, 15, 8),
            bgcolor="#121212",
            border_radius=12,
            border=ft.Border.all(1.5, "#FFFFFF"),
            content=ft.Text("بيانات المعترف", size=22, weight=ft.FontWeight.BOLD, color="#FFFFFF")
        )

        name_card = ft.Container(
            padding=ft.Padding(20, 10, 20, 10),
            bgcolor="#121212",
            border_radius=14,
            border=ft.Border.all(1.5, "#FFFFFF"),
            content=ft.Text(row["name"], size=24, weight=ft.FontWeight.BOLD, color="#FFFFFF", text_align=ft.TextAlign.CENTER)
        )

        profile_card = ft.Container(
            width=480,
            padding=20,
            border_radius=24,
            bgcolor="#121212EE",
            border=ft.Border.all(2, "#FFFFFF"),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=14,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[profile_title, back_button]),
                    profile_image,
                    name_card,
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=10, controls=[edit_btn, delete_btn]),
                    info_row(ft.Icons.CAKE_OUTLINED, "تاريخ الميلاد / السن", row["birth_date"]),
                    info_row(ft.Icons.PHONE_OUTLINED, "رقم الهاتف", row["phone"]),
                    info_row(ft.Icons.LOCATION_ON_OUTLINED, "العنوان", row["address"]),
                    info_row(ft.Icons.EVENT_OUTLINED, "آخر مرة اعترف", row["last_confession"]),
                    ft.Container(padding=15, border_radius=18, bgcolor="#121212", border=ft.Border.all(1.5, "#FFFFFF"), content=ft.Column(spacing=8, controls=family_controls)),
                    ft.Container(
                        padding=15, 
                        border_radius=18, 
                        bgcolor="#121212", 
                        border=ft.Border.all(1.5, "#FFFFFF"),
                        content=ft.Column(
                            spacing=6, 
                            controls=[
                                ft.Text("ملاحظات", size=18, weight=ft.FontWeight.BOLD, color="#FFFFFF"), 
                                ft.Text(row["notes"] or "لا توجد ملاحظات", size=15, weight=ft.FontWeight.BOLD, color="#EEEEEE")
                            ]
                        )
                    ),
                ],
            )
        )

        page.add(church_background(ft.Container(expand=True, alignment=ft.Alignment(0, 0), padding=20, content=profile_card)))
        page.update()

    async def intro():
        page.controls.clear()

        animated_text = ft.Container(
            opacity=0,
            animate_opacity=1000,
            offset=ft.Offset(0, 0.2),
            animate_offset=ft.Animation(1000, ft.AnimationCurve.EASE_OUT),
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
                controls=[
                    ft.Text("✝", size=60, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                    ft.Text("راعي الرعاة", size=32, weight=ft.FontWeight.BOLD, color="#FFFFFF", text_align=ft.TextAlign.CENTER),
                    ft.Text("كنيسة الشهيد العظيم أبي سيفين والقديسة دميانة", size=16, weight=ft.FontWeight.BOLD, color="#DDDDDD", text_align=ft.TextAlign.CENTER),
                ],
            )
        )

        first_screen = ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=animated_text
        )

        page.add(church_background(first_screen))
        page.update()

        await asyncio.sleep(0.3)
        animated_text.opacity = 1
        animated_text.offset = ft.Offset(0, 0)
        page.update()

        await asyncio.sleep(3)

        page.controls.clear()

        priest_screen = ft.Container(
            expand=True,
            bgcolor="#000000",
            alignment=ft.Alignment(0, 0),
            content=ft.Image(
                src="church_priest.png",
                fit=ft.BoxFit.CONTAIN,
                width=float("inf"),
                height=float("inf"),
            )
        )

        page.add(priest_screen)
        page.update()

        await asyncio.sleep(3)

        show_home()

    page.run_task(intro)

ft.run(main, assets_dir=ASSETS_DIR, upload_dir=UPLOADS_DIR)