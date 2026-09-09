import asyncio
import base64
import json
import mimetypes
import os
import sqlite3
import shutil
from datetime import datetime
import flet as ft

# لاستخدام Google Drive
try:
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    PYDRIVE_AVAILABLE = True
except ImportError:
    PYDRIVE_AVAILABLE = False

# =========================================================
# PATHS & DIRECTORIES
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "church.db")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")

for folder in [UPLOADS_DIR, BACKUPS_DIR, ASSETS_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)

def get_asset_path(filename):
    asset_p = os.path.join(ASSETS_DIR, filename)
    if os.path.exists(asset_p):
        return asset_p
    base_p = os.path.join(BASE_DIR, filename)
    if os.path.exists(base_p):
        return base_p
    return filename

# =========================================================
# DATABASE & BACKUP LOGIC (LOCAL & GOOGLE DRIVE)
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
    """نسخ احتياطي محلي تلقائي"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_file = os.path.join(BACKUPS_DIR, f"auto_backup_{timestamp}.db")
        latest_backup = os.path.join(BACKUPS_DIR, "latest_backup.db")
        
        shutil.copy2(DB_FILE, backup_file)
        shutil.copy2(DB_FILE, latest_backup)
        
        all_backups = sorted([os.path.join(BACKUPS_DIR, f) for f in os.listdir(BACKUPS_DIR) if f.startswith("auto_backup_")])
        if len(all_backups) > 5:
            for old_b in all_backups[:-5]:
                os.remove(old_b)
        return latest_backup
    except Exception as e:
        print(f"Auto backup error: {e}")
        return None

def backup_to_google_drive():
    """رفع النسخة الاحتياطية سحابياً إلى Google Drive"""
    if not PYDRIVE_AVAILABLE or not os.path.exists(DB_FILE):
        return False
    try:
        gauth = GoogleAuth()
        secrets_file = os.path.join(BASE_DIR, "client_secrets.json")
        if os.path.exists(secrets_file):
            gauth.LoadClientConfigFile(secrets_file)
        gauth.LocalWebserverAuth()
        drive = GoogleDrive(gauth)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"raei_backup_{timestamp}.db"

        file_drive = drive.CreateFile({'title': file_name})
        file_drive.SetContentFile(DB_FILE)
        file_drive.Upload()
        return True
    except Exception as e:
        print(f"Google Drive Backup Error: {e}")
        return False

def save_confessor(name, birth_date, phone, address, last_confession, has_family, family_members, notes, photo, confessor_id=None):
    conn = get_db()
    family_json = json.dumps(family_members, ensure_ascii=False)
    
    if confessor_id:
        conn.execute(
            """
            UPDATE confessors 
            SET name=?, birth_date=?, phone=?, address=?, last_confession=?, has_family=?, family_json=?, notes=?, photo=?
            WHERE id=?
            """,
            (name, birth_date, phone, address, last_confession, 1 if has_family else 0, family_json, notes, photo, confessor_id)
        )
    else:
        conn.execute(
            """
            INSERT INTO confessors (name, birth_date, phone, address, last_confession, has_family, family_json, notes, photo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, birth_date, phone, address, last_confession, 1 if has_family else 0, family_json, notes, photo)
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
# MAIN APPLICATION
# =========================================================

def main(page: ft.Page):
    init_db()

    page.title = "راعي الرعاة"
    page.padding = 0
    page.spacing = 0
    page.bgcolor = "#000000"
    page.rtl = True

    file_picker = ft.FilePicker()
    page.services.append(file_picker)

    current_photo = {"value": ""}
    family_inputs = []

    def show_message(message):
        page.snack_bar = ft.SnackBar(content=ft.Text(message, text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD, color="#FFFFFF"))
        page.snack_bar.open = True
        page.update()

    def church_background(content):
        return ft.Stack(
            expand=True,
            controls=[
                ft.Image(
                    src=get_asset_path("church_main.webp"),
                    width=float("inf"),
                    height=float("inf"),
                    fit=ft.ImageFit.COVER,
                ),
                ft.Container(expand=True, bgcolor="#000000D9"),
                content,
            ],
        )

    # =====================================================
    # BACKUP ACTIONS
    # =====================================================

    def export_backup_action(e):
        latest = auto_backup()
        if latest and os.path.exists(latest):
            show_message(f"تم إنشاء النسخة الاحتياطية بنجاح:\n{latest}")
        else:
            show_message("حدث خطأ أثناء إنشاء النسخة الاحتياطية")

    def gdrive_backup_action(e):
        show_message("جاري الرفع إلى Google Drive...")
        if backup_to_google_drive():
            show_message("تم الرفع إلى Google Drive بنجاح!")
        else:
            show_message("فشل الرفع سحابياً (تأكد من ملف client_secrets.json وإعدادات المكتبة)")

    async def restore_backup_action(e):
        try:
            files = await file_picker.pick_files(allow_multiple=False, dialog_title="اختر ملف النسخة الاحتياطية (.db)")
            if files and files[0].path:
                selected_db = files[0].path
                if selected_db.endswith(".db"):
                    shutil.copy2(selected_db, DB_FILE)
                    show_message("تمت استعادة البيانات بنجاح!")
                    show_home()
                else:
                    show_message("يرجى اختيار ملف قاعدة بيانات صحيح (.db)")
        except Exception as ex:
            show_message(f"خطأ في الاستعادة: {ex}")

    # =====================================================
    # HOME
    # =====================================================

    def show_home(e=None):
        page.controls.clear()

        # إضافة اللوجو
        logo_image = ft.Image(
            src=get_asset_path("icon.png"),
            width=80,
            height=80,
            fit=ft.ImageFit.CONTAIN
        )

        title = ft.Text("تطبيق راعي الرعاة", size=26, weight=ft.FontWeight.BOLD, color="#FFFFFF", text_align=ft.TextAlign.CENTER)
        subtitle = ft.Text("كنيسة الشهيد العظيم أبي سيفين والقديسة دميانة", size=15, weight=ft.FontWeight.BOLD, color="#EEEEEE", text_align=ft.TextAlign.CENTER)

        confession_card = ft.Container(
            width=340,
            padding=22,
            border_radius=22,
            bgcolor="#121212",
            border=ft.Border.all(1.5, "#FFFFFF66"),
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

        backup_btn = ft.Button("نسخة محليّة", icon=ft.Icons.CLOUD_UPLOAD, on_click=export_backup_action)
        gdrive_btn = ft.Button("نسخة Google Drive", icon=ft.Icons.ADD_TO_DRIVE, on_click=gdrive_backup_action)
        restore_btn = ft.Button("استعادة نسخة", icon=ft.Icons.CLOUD_DOWNLOAD, on_click=restore_backup_action)

        main_card = ft.Container(
            width=450,
            padding=25,
            border_radius=28,
            bgcolor="#121212",
            border=ft.Border.all(1.5, "#FFFFFF66"),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
                controls=[
                    logo_image,
                    title, 
                    subtitle, 
                    ft.Container(height=5), 
                    confession_card,
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, wrap=True, spacing=8, controls=[backup_btn, gdrive_btn, restore_btn])
                ],
            ),
        )

        content = ft.Container(expand=True, alignment=ft.Alignment(0, 0), padding=20, content=main_card)
        page.add(church_background(content))
        page.update()

    # =====================================================
    # CONFESSIONS LIST
    # =====================================================

    def show_confessions(search_value=""):
        page.controls.clear()

        search_field = ft.TextField(
            label="بحث عن معترف",
            hint_text="اكتب الاسم",
            width=330,
            prefix_icon=ft.Icons.SEARCH,
            bgcolor="#121212",
            color="#FFFFFF",
            label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD),
            border_color="#FFFFFF66",
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
                        padding=35,
                        alignment=ft.Alignment(0, 0),
                        bgcolor="#121212",
                        border_radius=18,
                        border=ft.Border.all(1.5, "#FFFFFF66"),
                        content=ft.Text("لا يوجد معترفين حتى الآن", size=16, weight=ft.FontWeight.BOLD, color="#FFFFFF", text_align=ft.TextAlign.CENTER),
                    )
                )
            else:
                for row in rows:
                    photo_src = row["photo"]
                    if photo_src and os.path.exists(photo_src):
                        image_control = ft.Image(src=photo_src, width=58, height=58, fit=ft.ImageFit.COVER, border_radius=29)
                    else:
                        image_control = ft.Container(
                            width=58,
                            height=58,
                            border_radius=29,
                            bgcolor="#FFFFFF20",
                            alignment=ft.Alignment(0, 0),
                            content=ft.Icon(ft.Icons.PERSON_OUTLINE, size=28, color="#FFFFFF"),
                        )

                    family_text = "لديه أسرة" if row["has_family"] else "بدون أسرة"

                    card = ft.Container(
                        padding=14,
                        border_radius=18,
                        bgcolor="#121212",
                        border=ft.Border.all(1.5, "#FFFFFF66"),
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
            border=ft.Border.all(1.5, "#FFFFFF66"),
            content=ft.Text("الاعترافات", size=24, weight=ft.FontWeight.BOLD, color="#FFFFFF")
        )

        content = ft.Container(
            expand=True,
            padding=20,
            content=ft.Column(
                expand=True,
                spacing=15,
                controls=[
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[header_title, back_button]),
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[search_field, search_button]),
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[add_button]),
                    ft.Divider(color="#FFFFFF55", height=10),
                    list_column,
                ],
            ),
        )

        page.add(church_background(content))
        refresh_list()

    # =====================================================
    # ADD/EDIT CONFESSOR FORM
    # =====================================================

    def add_family_member_ui(family_column, name_val="", rel_val=""):
        member_name = ft.TextField(label="اسم فرد الأسرة", width=210, bgcolor="#1A1A1A", color="#FFFFFF", label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD), border_color="#FFFFFF66", border_radius=12, value=name_val)
        relation = ft.TextField(label="صلة القرابة", width=160, bgcolor="#1A1A1A", color="#FFFFFF", label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD), border_color="#FFFFFF66", border_radius=12, value=rel_val)

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
            border=ft.Border.all(1, "#FFFFFF44"),
            content=ft.Row(wrap=True, controls=[member_name, relation, ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#FFFFFF", on_click=delete_member)]),
        )

        family_column.controls.append(member_container)
        page.update()

    def show_form_confessor(edit_id=None):
        page.controls.clear()
        family_inputs.clear()

        edit_data = get_confessor(edit_id) if edit_id else None
        current_photo["value"] = edit_data["photo"] if edit_data else ""

        name_field = ft.TextField(label="الاسم *", width=350, bgcolor="#121212", color="#FFFFFF", label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD), border_color="#FFFFFF66", border_radius=14, value=edit_data["name"] if edit_data else "")
        birth_field = ft.TextField(label="تاريخ الميلاد / السن", hint_text="15/08/1985", width=350, bgcolor="#121212", color="#FFFFFF", label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD), border_color="#FFFFFF66", border_radius=14, value=edit_data["birth_date"] if edit_data else "")
        phone_field = ft.TextField(label="رقم الهاتف", width=350, keyboard_type=ft.KeyboardType.PHONE, bgcolor="#121212", color="#FFFFFF", label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD), border_color="#FFFFFF66", border_radius=14, value=edit_data["phone"] if edit_data else "")
        address_field = ft.TextField(label="العنوان", width=350, multiline=True, min_lines=2, max_lines=4, bgcolor="#121212", color="#FFFFFF", label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD), border_color="#FFFFFF66", border_radius=14, value=edit_data["address"] if edit_data else "")
        last_confession_field = ft.TextField(label="آخر مرة اعترف إمتى؟", hint_text="01/09/2026", width=350, bgcolor="#121212", color="#FFFFFF", label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD), border_color="#FFFFFF66", border_radius=14, value=edit_data["last_confession"] if edit_data else "")
        notes_field = ft.TextField(label="ملاحظات", width=350, multiline=True, min_lines=3, max_lines=6, bgcolor="#121212", color="#FFFFFF", label_style=ft.TextStyle(color="#FFFFFF", weight=ft.FontWeight.BOLD), border_color="#FFFFFF66", border_radius=14, value=edit_data["notes"] if edit_data else "")

        photo_preview = ft.Image(src=current_photo["value"], width=120, height=120, fit=ft.ImageFit.COVER, border_radius=60, visible=bool(current_photo["value"]))
        photo_placeholder = ft.Container(width=120, height=120, border_radius=60, bgcolor="#FFFFFF20", alignment=ft.Alignment(0, 0), visible=not bool(current_photo["value"]), content=ft.Icon(ft.Icons.PERSON_OUTLINE, size=48, color="#FFFFFF"))

        async def choose_photo(e):
            try:
                files = await file_picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE, with_data=True)
                if not files or not files[0].bytes:
                    return

                selected_file = files[0]
                save_path = os.path.join(UPLOADS_DIR, f"photo_{os.urandom(4).hex()}_{selected_file.name}")
                with open(save_path, "wb") as f:
                    f.write(selected_file.bytes)

                current_photo["value"] = save_path
                photo_preview.src = save_path
                photo_preview.visible = True
                photo_placeholder.visible = False
                page.update()
            except Exception as ex:
                show_message(f"خطأ في اختيار الصورة: {ex}")

        photo_button = ft.Button("إضافة صورة", icon=ft.Icons.CAMERA_ALT_OUTLINED, on_click=choose_photo)
        photo_area = ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10, controls=[photo_placeholder, photo_preview, photo_button])

        family_switch = ft.Switch(label="لديه أسرة", value=bool(edit_data["has_family"]) if edit_data else False)
        family_column = ft.Column(spacing=8, visible=family_switch.value)
        add_family_button = ft.Button("إضافة فرد للأسرة", icon=ft.Icons.PERSON_ADD_ALT_1, visible=family_switch.value, on_click=lambda e: add_family_member_ui(family_column))

        def family_changed(e):
            family_column.visible = family_switch.value
            add_family_button.visible = family_switch.value
            page.update()

        family_switch.on_change = family_changed
        family_section = ft.Container(width=380, padding=15, border_radius=18, bgcolor="#121212", border=ft.Border.all(1.5, "#FFFFFF66"), content=ft.Column(spacing=10, controls=[family_switch, family_column, add_family_button]))

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
                show_message("اكتب اسم المعترف أولًا")
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

            show_message("تم حفظ البيانات بنجاح")
            show_confessions()

        back_button = ft.Button("رجوع", icon=ft.Icons.ARROW_BACK, on_click=lambda e: show_confessions())
        save_button = ft.Button("حفظ المعترف", icon=ft.Icons.SAVE_OUTLINED, on_click=save_person)

        form_title = ft.Container(
            padding=ft.Padding(15, 8, 15, 8),
            bgcolor="#121212",
            border_radius=12,
            border=ft.Border.all(1.5, "#FFFFFF66"),
            content=ft.Text("تعديل / إنشاء معترف", size=24, weight=ft.FontWeight.BOLD, color="#FFFFFF")
        )

        form = ft.Column(
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
                ft.Container(height=30),
            ],
        )

        page.add(church_background(ft.Container(expand=True, padding=20, content=form)))
        page.update()

    # =====================================================
    # PROFILE VIEW
    # =====================================================

    def show_profile(confessor_id):
        row = get_confessor(confessor_id)
        if not row:
            show_message("لم يتم العثور على البيانات")
            return

        page.controls.clear()

        photo_src = row["photo"]
        if photo_src and os.path.exists(photo_src):
            profile_image = ft.Image(src=photo_src, width=140, height=140, fit=ft.ImageFit.COVER, border_radius=70)
        else:
            profile_image = ft.Container(
                width=140, 
                height=140, 
                border_radius=70, 
                bgcolor="#FFFFFF20", 
                alignment=ft.Alignment(0, 0), 
                content=ft.Icon(ft.Icons.PERSON_OUTLINE, size=60, color="#FFFFFF")
            )

        def info_row(icon, title, value):
            return ft.Container(
                padding=14,
                border_radius=14,
                bgcolor="#121212",
                border=ft.Border.all(1.5, "#FFFFFF66"),
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
                            bgcolor="#1A1A1A",
                            border=ft.Border.all(1, "#FFFFFF44"),
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.PERSON_OUTLINE, size=22, color="#FFFFFF"),
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
            show_message("تم حذف المعترف بنجاح")
            show_confessions()

        edit_btn = ft.Button("تعديل البيانات", icon=ft.Icons.EDIT, on_click=lambda e: show_form_confessor(confessor_id))
        delete_btn = ft.Button("حذف المعترف", icon=ft.Icons.DELETE, bgcolor="#880000", color="#FFFFFF", on_click=confirm_delete)
        back_button = ft.Button("رجوع", icon=ft.Icons.ARROW_BACK, on_click=lambda e: show_confessions())

        profile_title = ft.Container(
            padding=ft.Padding(15, 8, 15, 8),
            bgcolor="#121212",
            border_radius=12,
            border=ft.Border.all(1.5, "#FFFFFF66"),
            content=ft.Text("بيانات المعترف", size=24, weight=ft.FontWeight.BOLD, color="#FFFFFF")
        )

        name_card = ft.Container(
            padding=ft.Padding(20, 10, 20, 10),
            bgcolor="#121212",
            border_radius=14,
            border=ft.Border.all(1.5, "#FFFFFF66"),
            content=ft.Text(row["name"], size=26, weight=ft.FontWeight.BOLD, color="#FFFFFF", text_align=ft.TextAlign.CENTER)
        )

        content = ft.Container(
            expand=True,
            padding=20,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
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
                    ft.Container(padding=15, border_radius=18, bgcolor="#121212", border=ft.Border.all(1.5, "#FFFFFF66"), content=ft.Column(spacing=8, controls=family_controls)),
                    ft.Container(
                        padding=15, 
                        border_radius=18, 
                        bgcolor="#121212", 
                        border=ft.Border.all(1.5, "#FFFFFF66"),
                        content=ft.Column(
                            spacing=6, 
                            controls=[
                                ft.Text("ملاحظات", size=19, weight=ft.FontWeight.BOLD, color="#FFFFFF"), 
                                ft.Text(row["notes"] or "لا توجد ملاحظات", size=15, weight=ft.FontWeight.BOLD, color="#EEEEEE")
                            ]
                        )
                    ),
                    ft.Container(height=30),
                ],
            ),
        )

        page.add(church_background(content))
        page.update()

    # =====================================================
    # INTRO SCREEN
    # =====================================================

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

        # إظهار صورة أبونا كاملة بدون زوم (ImageFit.CONTAIN)
        priest_screen = ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=ft.Image(
                src=get_asset_path("church_priest.png"),
                fit=ft.ImageFit.CONTAIN,
            )
        )

        page.add(church_background(priest_screen))
        page.update()

        await asyncio.sleep(3)

        show_home()

    page.run_task(intro)

ft.app(target=main)