import asyncio
import json
import os
import sqlite3
from openpyxl import Workbook, load_workbook
import shutil
import subprocess
from datetime import datetime
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

def resolve_asset(filename):
    """دالة ذكية للتحقق من مسار الصورة سواء في assets أو uploads أو كمسار مطلق"""
    if not filename:
        return ""
    name_only = os.path.basename(filename)
    
    # 1. فحص مجلد assets المحلي بالمحرك المطلق
    local_asset = os.path.join(ASSETS_DIR, name_only)
    if os.path.exists(local_asset):
        return local_asset
        
    # 2. فحص مجلد uploads المحلي بالمحرك المطلق
    upload_path = os.path.join(UPLOADS_DIR, name_only)
    if os.path.exists(upload_path):
        return upload_path

    # 3. لو تم إرسال مسار مطلق مسبقاً
    if os.path.exists(filename):
        return filename

    return name_only

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
    clean_photo_path = os.path.basename(photo) if photo else ""
    
    if confessor_id:
        conn.execute(
            """
            UPDATE confessors 
            SET name=?, birth_date=?, phone=?, address=?, last_confession=?, has_family=?, family_json=?, notes=?, photo=?
            WHERE id=?
            """,
            (name, birth_date, phone, address, last_confession, 1 if has_family else 0, family_json, notes, clean_photo_path, confessor_id)
        )
    else:
        conn.execute(
            """
            INSERT INTO confessors (name, birth_date, phone, address, last_confession, has_family, family_json, notes, photo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, birth_date, phone, address, last_confession, 1 if has_family else 0, family_json, notes, clean_photo_path)
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


# =========================================================
# EXCEL SHEET BACKUP / UPLOAD
# =========================================================

SHEET_HEADERS = [
    "ID", "الاسم", "تاريخ الميلاد", "الهاتف", "العنوان",
    "آخر اعتراف", "لديه أسرة", "بيانات الأسرة", "ملاحظات", "الصورة"
]

def backup_sheet():
    """Export all confessors to an Excel .xlsx file inside backups."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(BACKUPS_DIR, f"backup_sheet_{timestamp}.xlsx")

        wb = Workbook()
        ws = wb.active
        ws.title = "الاعترافات"
        ws.append(SHEET_HEADERS)

        for row in get_confessors():
            # رقم الهاتف يُكتب كنص وليس رقمًا حتى يحتفظ Excel بالصفر في البداية.
            phone = str(row["phone"] or "").strip()

            ws.append([
                row["id"],
                row["name"] or "",
                row["birth_date"] or "",
                phone,
                row["address"] or "",
                row["last_confession"] or "",
                "نعم" if row["has_family"] else "لا",
                row["family_json"] or "",
                row["notes"] or "",
                row["photo"] or "",
            ])

            # العمود D (الهاتف) Text format حتى 012... يظل 012... في Excel.
            phone_cell = ws.cell(row=ws.max_row, column=4)
            phone_cell.number_format = "@"

        # تنسيق عمود الهاتف بالكامل كنص، بما فيه الخلايا الفارغة الجديدة.
        for cell in ws["D"]:
            cell.number_format = "@"

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        widths = [8, 28, 16, 18, 32, 18, 14, 35, 35, 25]
        for idx, width in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + idx)].width = width

        wb.save(path)
        return path
    except Exception as e:
        print(f"Excel backup error: {e}")
        return None


def upload_sheet(path):
    """Import rows from an Excel sheet into the confessors table."""
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        if not rows:
            return 0, "الشيت فارغ"

        header = [str(x).strip() if x is not None else "" for x in rows[0]]
        header_map = {name: i for i, name in enumerate(header)}

        def value(row, *names):
            for name in names:
                if name in header_map:
                    i = header_map[name]
                    return row[i] if i < len(row) else ""
            return ""

        imported = 0
        conn = get_db()

        for row in rows[1:]:
            name = str(value(row, "الاسم", "Name") or "").strip()
            if not name:
                continue

            birth_date = str(value(row, "تاريخ الميلاد", "Birth Date") or "")
            phone = str(value(row, "الهاتف", "Phone") or "")
            address = str(value(row, "العنوان", "Address") or "")
            last_confession = str(value(row, "آخر اعتراف", "Last Confession") or "")
            has_family_raw = str(value(row, "لديه أسرة", "Has Family") or "").strip().lower()
            has_family = 1 if has_family_raw in ("نعم", "yes", "1", "true") else 0
            family_json = str(value(row, "بيانات الأسرة", "Family") or "")
            notes = str(value(row, "ملاحظات", "Notes") or "")
            photo = os.path.basename(str(value(row, "الصورة", "Photo") or ""))

            conn.execute(
                """
                INSERT INTO confessors
                (name, birth_date, phone, address, last_confession,
                 has_family, family_json, notes, photo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name, birth_date, phone, address, last_confession,
                    has_family, family_json, notes, photo
                )
            )
            imported += 1

        conn.commit()
        conn.close()
        auto_backup()
        return imported, None

    except Exception as e:
        print(f"Excel upload error: {e}")
        return 0, str(e)

# =========================================================
# MAIN APPLICATION
# =========================================================

def main(page: ft.Page):
    init_db()

    page.title = "رَاعِي الرُّعَاةِ"
    page.padding = 0
    page.spacing = 0
    page.bgcolor = "#000000"
    page.rtl = True
    page.assets_dir = ASSETS_DIR

    file_picker = ft.FilePicker()
    page.services.append(file_picker)

    sheet_picker = ft.FilePicker()
    page.services.append(sheet_picker)

    current_photo = {"value": ""}
    family_inputs = []

    def show_snack(msg):
        snack = ft.SnackBar(content=ft.Text(msg, text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD, color="#FFFFFF"))
        page.overlay.append(snack)
        snack.open = True
        page.update()

    def church_background(content):
        # استخدام المسار المطلق المباشر لمنع أي شاشة سوداء
        bg_path = os.path.join(ASSETS_DIR, "church_main.webp")
        return ft.Stack(
            expand=True,
            controls=[
                ft.Image(
                    src=bg_path,
                    width=float("inf"),
                    height=float("inf"),
                    fit=ft.BoxFit.COVER,
                ),
                ft.Container(expand=True, bgcolor="#00000055"),
                content,
            ],
        )

    def export_backup_action(e):
        try:
            b_path = auto_backup()
            if b_path and os.path.exists(b_path):
                show_snack(f"تم حفظ النسخة بنجاح:\n{os.path.basename(b_path)}")
            else:
                show_snack("فشل إنشاء النسخة الاحتياطية")
        except Exception as ex:
            show_snack(f"خطأ: {ex}")

    def export_sheet_action(e):
        try:
            path = backup_sheet()
            if path and os.path.exists(path):
                show_snack(f"تم حفظ الشيت بنجاح:\n{os.path.basename(path)}")
            else:
                show_snack("فشل إنشاء Backup Sheet")
        except Exception as ex:
            show_snack(f"خطأ في Backup Sheet: {ex}")

    def on_sheet_result(e):
        try:
            if e.files and len(e.files) > 0:
                selected = e.files[0]
                if selected.path:
                    imported, err = upload_sheet(selected.path)
                    if err:
                        show_snack(f"خطأ في Upload Sheet: {err}")
                    else:
                        show_snack(f"تم رفع الشيت بنجاح — تمت إضافة {imported} سجل")
                        show_home()
        except Exception as ex:
            show_snack(f"خطأ في Upload Sheet: {ex}")

    sheet_picker.on_result = on_sheet_result

    async def upload_sheet_click(e):
        await sheet_picker.pick_files(
            allow_multiple=False,
            dialog_title="اختر ملف Excel",
        )

    def show_home(e=None):
        page.controls.clear()

        title = ft.Container(
            padding=ft.Padding(18, 8, 18, 8),
            border_radius=24,
            bgcolor="#3B2416DD",
            border=ft.Border.all(1.5, "#D6A64A"),
            shadow=ft.BoxShadow(
                blur_radius=16,
                spread_radius=1,
                offset=ft.Offset(0, 3),
            ),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=13,
                controls=[
                    ft.Text("✣", size=26, color="#E0B45C"),
                    ft.Text(
                        "رَاعِي الرُّعَاةِ",
                        size=42,
                        weight=ft.FontWeight.BOLD,
                        color="#FFE3A0",
                        text_align=ft.TextAlign.CENTER,
                        font_family="Amiri",
                    ),
                    ft.Text("✣", size=26, color="#E0B45C"),
                ],
            ),
        )
        subtitle = ft.Text(
            "كنيسة الشهيد العظيم أبي سيفين والقديسة دميانة",
            size=16,
            weight=ft.FontWeight.BOLD,
            color="#F4E4C1",
            text_align=ft.TextAlign.CENTER,
        )

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
                        width=120,
                        height=120,
                        border_radius=24,
                        bgcolor="#3A2215",
                        alignment=ft.Alignment(0, 0),
                        ink=True,
                        content=ft.Image(
                            src="cross_button_complete_v2.png",
                            width=120,
                            height=120,
                            fit=ft.BoxFit.CONTAIN,
                        ),
                    ),
                    ft.Text("الاعترافات", size=22, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                    ft.Text("إدارة بيانات المعترفين", size=13, weight=ft.FontWeight.BOLD, color="#DDDDDD"),
                ],
            ),
        )

        upload_sheet_btn = ft.Button(
            "Upload Sheet",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=upload_sheet_click,
        )
        backup_sheet_btn = ft.Button(
            "Backup Sheet",
            icon=ft.Icons.DOWNLOAD,
            on_click=export_sheet_action,
        )
        main_card = ft.Container(
            width=450,
            padding=25,
            border_radius=28,
            bgcolor="#121212EE",
            border=ft.Border.all(2, "#FFFFFF"),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
                controls=[
                    title, 
                    subtitle, 
                    ft.Container(height=5), 
                    confession_card,
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        wrap=True,
                        spacing=8,
                        controls=[upload_sheet_btn, backup_sheet_btn],
                    ),
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
            border_color="#FFFFFF",
            border_radius=14,
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
                    photo_src = resolve_asset(row["photo"])
                    if photo_src:
                        image_control = ft.Image(src=photo_src, width=58, height=58, fit=ft.BoxFit.COVER, border_radius=29)
                    else:
                        image_control = ft.Container(
                            width=58,
                            height=58,
                            border_radius=29,
                            bgcolor="#FFFFFF",  # خلفية بيضاء
                            alignment=ft.Alignment(0, 0),
                            content=ft.Icon(ft.Icons.PERSON, size=28, color="#000000"),
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
        # أفراد الأسرة يتم اختيارهم من المعترفين الموجودين بالفعل.
        relation_options = [
            ("زوج", ft.Icons.FAVORITE),
            ("زوجة", ft.Icons.FAVORITE_BORDER),
            ("ابن", ft.Icons.BOY),
            ("ابنة", ft.Icons.GIRL),
            ("أب", ft.Icons.MAN),
            ("أم", ft.Icons.WOMAN),
            ("أخ", ft.Icons.PERSON),
            ("أخت", ft.Icons.PERSON_OUTLINE),
            ("جد", ft.Icons.ELDERLY),
            ("جدة", ft.Icons.ELDERLY_WOMAN),
            ("حفيد", ft.Icons.CHILD_CARE),
            ("حفيدة", ft.Icons.CHILD_CARE),
            ("قريب", ft.Icons.GROUP),
            ("قريبة", ft.Icons.GROUP_OUTLINED),
            ("أخرى", ft.Icons.PERSON_OUTLINE),
        ]
        relation_icons = dict(relation_options)

        selected = {"id": None, "name": name_val}

        name_field = ft.TextField(
            label="اسم فرد الأسرة",
            width=230,
            value=name_val,
            filled=True,
            bgcolor="#121212",
            color="#FFFFFF",
            label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD),
            border_color="#FFFFFF",
            border_radius=12,
            prefix_icon=ft.Icons.PERSON_SEARCH,
        )

        suggestions = ft.Column(
            spacing=2,
            visible=False,
            scroll=ft.ScrollMode.AUTO,
        )

        relation_icon = ft.Icon(
            relation_icons.get(rel_val, ft.Icons.FAMILY_RESTROOM),
            size=24,
            color="#9CCBFF",
        )

        relation = ft.Dropdown(
            label="صلة القرابة",
            width=160,
            value=rel_val if rel_val in relation_icons else None,
            filled=True,
            bgcolor="#121212",
            color="#FFFFFF",
            label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD),
            border_color="#FFFFFF",
            border_radius=12,
            options=[
                ft.DropdownOption(key=key, text=key)
                for key, _ in relation_options
            ],
        )

        def choose_person(person):
            selected["id"] = person["id"]
            selected["name"] = person["name"]
            name_field.value = person["name"]
            suggestions.visible = False
            page.update()

        def refresh_suggestions(e=None):
            query = (name_field.value or "").strip()
            suggestions.controls.clear()

            if len(query) < 1:
                suggestions.visible = False
                page.update()
                return

            matches = get_confessors(query)

            if matches:
                for person in matches[:8]:
                    person_id = person["id"]
                    person_name = person["name"]

                    suggestions.controls.append(
                        ft.Container(
                            padding=ft.Padding(10, 7, 10, 7),
                            border_radius=10,
                            bgcolor="#222222",
                            border=ft.Border.all(1, "#FFFFFF55"),
                            ink=True,
                            on_click=lambda e, p={"id": person_id, "name": person_name}: choose_person(p),
                            content=ft.Row(
                                spacing=8,
                                controls=[
                                    ft.Icon(ft.Icons.PERSON, size=20, color="#9CCBFF"),
                                    ft.Text(
                                        person_name,
                                        size=15,
                                        weight=ft.FontWeight.BOLD,
                                        color="#FFFFFF",
                                        expand=True,
                                    ),
                                ],
                            ),
                        )
                    )
                suggestions.visible = True
            else:
                suggestions.visible = False

            page.update()

        name_field.on_change = refresh_suggestions

        def relation_changed(e):
            relation_icon.icon = relation_icons.get(
                relation.value or "",
                ft.Icons.FAMILY_RESTROOM,
            )
            page.update()

        relation.on_change = relation_changed

        item_ref = {
            "name_field": name_field,
            "rel_field": relation,
            "person_id": selected,
        }
        family_inputs.append(item_ref)

        def delete_member(e):
            if member_container in family_column.controls:
                family_column.controls.remove(member_container)
            if item_ref in family_inputs:
                family_inputs.remove(item_ref)
            page.update()

        member_container = ft.Container(
            width=380,
            padding=10,
            border_radius=16,
            bgcolor="#121212",
            border=ft.Border.all(1, "#FFFFFF"),
            content=ft.Column(
                spacing=7,
                controls=[
                    ft.Row(
                        spacing=7,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            relation_icon,
                            name_field,
                            relation,
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color="#FFFFFF",
                                tooltip="حذف فرد",
                                on_click=delete_member,
                            ),
                        ],
                    ),
                    ft.Container(
                        margin=ft.Margin(0, -2, 0, 0),
                        padding=ft.Padding(4, 0, 4, 4),
                        content=suggestions,
                    ),
                ],
            ),
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
                border_color="#FFFFFF",
                border_radius=14,
                value=value
            )

        name_field = create_styled_textfield("الاسم *", value=edit_data["name"] if edit_data else "")
        birth_field = create_styled_textfield("تاريخ الميلاد / السن", hint="15/08/1985", value=edit_data["birth_date"] if edit_data else "")
        phone_field = create_styled_textfield("رقم الهاتف", keyboard_type=ft.KeyboardType.PHONE, value=edit_data["phone"] if edit_data else "")
        address_field = create_styled_textfield("العنوان", multiline=True, min_lines=2, max_lines=4, value=edit_data["address"] if edit_data else "")
        last_confession_field = create_styled_textfield("آخر مرة اعترف إمتى؟", hint="01/09/2026", value=edit_data["last_confession"] if edit_data else "")
        notes_field = create_styled_textfield("ملاحظات", multiline=True, min_lines=3, max_lines=6, value=edit_data["notes"] if edit_data else "")

        photo_preview = ft.Image(
            src=resolve_asset(current_photo["value"]), 
            width=120, 
            height=120, 
            fit=ft.BoxFit.COVER, 
            border_radius=60, 
            visible=bool(current_photo["value"])
        )
        photo_placeholder = ft.Container(
            width=120, 
            height=120, 
            border_radius=60, 
            bgcolor="#FFFFFF",  # خلفية بيضاء
            border=ft.Border.all(2, "#FFFFFF"), 
            alignment=ft.Alignment(0, 0), 
            visible=not bool(current_photo["value"]), 
            content=ft.Icon(ft.Icons.PERSON, size=48, color="#000000")
        )

        photo_picker = ft.FilePicker()
        page.services.append(photo_picker)

        def on_photo_picked(e):
            try:
                if e.files and len(e.files) > 0:
                    selected_file = e.files[0]
                    target_name = f"confessor_{os.urandom(4).hex()}.jpg"
                    target_path = os.path.join(UPLOADS_DIR, target_name)

                    if selected_file.path and os.path.exists(selected_file.path):
                        shutil.copy2(selected_file.path, target_path)
                    current_photo["value"] = target_path
                    photo_preview.src = resolve_asset(target_path)
                    photo_preview.visible = True
                    photo_placeholder.visible = False
                    page.update()
            except Exception as ex:
                show_snack(f"خطأ حفظ الصورة: {ex}")

        photo_picker.on_result = on_photo_picked

        async def pick_photo_click(e):
            await photo_picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)

        photo_button = ft.Button("إضافة صورة", icon=ft.Icons.CAMERA_ALT_OUTLINED, on_click=pick_photo_click)
        photo_area = ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10, controls=[photo_placeholder, photo_preview, photo_button])

        family_switch = ft.Switch(
            label="لديه أسرة",
            value=bool(edit_data["has_family"]) if edit_data else False,
        )
        family_column = ft.Column(
            spacing=8,
            visible=family_switch.value,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO,
        )
        add_family_button = ft.Button(
            "إضافة فرد للأسرة",
            icon=ft.Icons.PERSON_ADD_ALT_1,
            visible=family_switch.value,
            on_click=lambda e: add_family_member_ui(family_column),
        )

        def family_changed(e):
            family_column.visible = family_switch.value
            add_family_button.visible = family_switch.value
            page.update()

        family_switch.on_change = family_changed
        family_section = ft.Container(
            width=380,
            padding=15,
            border_radius=18,
            bgcolor="#121212",
            border=ft.Border.all(1.5, "#FFFFFF"),
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.FAMILY_RESTROOM, size=24, color="#9CCBFF"),
                            family_switch,
                        ],
                    ),
                    family_column,
                    add_family_button,
                ],
            ),
        )

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
                        member_data = {"name": m_name, "relation": m_rel}
                        person_ref = item.get("person_id", {})
                        if person_ref.get("id") is not None:
                            member_data["person_id"] = person_ref["id"]
                        parsed_family.append(member_data)

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

        photo_src = resolve_asset(row["photo"])
        if photo_src:
            profile_image = ft.Image(src=photo_src, width=140, height=140, fit=ft.BoxFit.COVER, border_radius=70)
        else:
            profile_image = ft.Container(
                width=140, 
                height=140, 
                border_radius=70, 
                bgcolor="#FFFFFF",  # خلفية بيضاء
                border=ft.Border.all(2, "#FFFFFF"),
                alignment=ft.Alignment(0, 0), 
                content=ft.Icon(ft.Icons.PERSON, size=60, color="#000000")
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
                    ft.Container(
                        padding=ft.Padding(20, 10, 20, 10),
                        border_radius=25,
                        bgcolor="#3B2416E8",
                        border=ft.Border.all(1.7, "#D6A64A"),
                        shadow=ft.BoxShadow(
                            blur_radius=20,
                            spread_radius=1,
                            offset=ft.Offset(0, 4),
                        ),
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=15,
                            controls=[
                                ft.Text("✣", size=30, color="#E0B45C"),
                                ft.Text(
                                    "رَاعِي الرُّعَاةِ",
                                    size=42,
                                    weight=ft.FontWeight.BOLD,
                                    color="#FFE3A0",
                                    text_align=ft.TextAlign.CENTER,
                                    font_family="Amiri",
                                ),
                                ft.Text("✣", size=30, color="#E0B45C"),
                            ],
                        ),
                    ),
                    ft.Text(
                        "كنيسة الشهيد العظيم أبي سيفين والقديسة دميانة",
                        size=15,
                        weight=ft.FontWeight.BOLD,
                        color="#F4E4C1",
                        text_align=ft.TextAlign.CENTER,
                    ),
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

        # افتتاحية صوتية: "رَاعِي الرُّعَاةِ"
        
        await asyncio.sleep(3)

        page.controls.clear()

        # =====================================================
        # شاشة صورة أبونا - تحميل مباشر من الملف
        # يدعم JPG / JPEG / PNG حتى لو تغير امتداد الصورة
        # =====================================================

        priest_candidates = [
            os.path.join(ASSETS_DIR, "church_priest.jpg"),
            os.path.join(ASSETS_DIR, "church_priest.jpeg"),
            os.path.join(ASSETS_DIR, "church_priest.png"),
        ]

        priest_path = next((p for p in priest_candidates if os.path.isfile(p)), None)

        if priest_path:
            priest_image = ft.Image(
                src=priest_path,
                fit=ft.BoxFit.CONTAIN,
                expand=True,
            )
        else:
            print("Priest image not found in assets folder.")
            priest_image = ft.Container(
                expand=True,
                alignment=ft.Alignment(0, 0),
                content=ft.Text(
                    "صورة أبونا غير موجودة داخل مجلد assets",
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    color="#FFFFFF",
                    text_align=ft.TextAlign.CENTER,
                ),
            )

        priest_screen = ft.Container(
            expand=True,
            bgcolor="#000000",
            alignment=ft.Alignment(0, 0),
            content=priest_image,
        )

        page.add(priest_screen)
        page.update()

        await asyncio.sleep(3)

        show_home()

    page.run_task(intro)

ft.run(main)
