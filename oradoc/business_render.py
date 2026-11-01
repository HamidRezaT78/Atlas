"""Business analysis document (Markdown, fa/en) from business.analyze_business(), optionally merged with the
Claude enrichment of business_ai. Pure function of its inputs; every table is validated to appear."""
from .business import VOCAB, name_phrase, phrase
from .render import FA_DIGITS, cell

ROLE = {
    "fa": {"staging": "موقت (ورود اولیه داده)", "reject_log": "ثبت رکوردهای ردشده", "audit_log": "سابقه و لاگ",
           "outbox": "صف ارسال / پردازش", "checkpoint": "دسته دریافت / همگام‌سازی", "reconciliation": "تطبیق و مغایرت‌گیری",
           "integration_log": "ارتباط با سرویس خارجی", "file_import": "بارگذاری فایل", "junction": "واسط (چند-به-چند)",
           "lookup": "اطلاعات پایه (کدینگ)", "security": "کاربران و دسترسی", "settings": "تنظیمات",
           "detail": "جزئیات (سطرهای وابسته)", "transaction": "تراکنشی / رویدادی", "master": "داده اصلی", "other": "نامشخص"},
    "en": {"staging": "Staging", "reject_log": "Rejected-record log", "audit_log": "Audit / history log",
           "outbox": "Outbox / work queue", "checkpoint": "Fetch / sync checkpoint", "reconciliation": "Reconciliation",
           "integration_log": "External-service exchange log", "file_import": "File import",
           "junction": "Link (many-to-many)", "lookup": "Reference / lookup", "security": "Users & access",
           "settings": "Settings", "detail": "Detail (child rows)", "transaction": "Transaction / event",
           "master": "Master data", "other": "Unclear"},
}

BASIS = {"fa": {"name": "نام", "relationship": "رابطه", "type": "نوع داده", "structure": "ساختار", "comment": "توضیح ثبت‌شده",
                "check": "CHECK", "ai": "هوش مصنوعی"},
         "en": {"name": "name", "relationship": "relationship", "type": "data type", "structure": "structure",
                "comment": "recorded comment", "check": "CHECK", "ai": "AI"}}

KIND = {"fa": {"pk": "شناسه", "fk": "ارجاع", "audit_time": "ممیزی", "audit_user": "ممیزی", "soft_delete": "حذف منطقی",
               "flag": "بله/خیر", "status": "وضعیت", "classifier": "دسته‌بندی", "money": "مالی", "count": "تعداد",
               "rate": "نرخ", "time": "زمان", "payload": "محتوای پیام", "external_ref": "شناسه سیستم خارجی",
               "file": "فایل", "error_info": "خطا / تلاش مجدد", "identifier": "شماره / کد", "text": "متن",
               "geo": "مکان", "other": "—", "sensitive_national_id": "حساس: شناسه ملی", "sensitive_personal": "حساس: شخصی",
               "sensitive_contact": "حساس: تماس", "sensitive_financial": "حساس: مالی", "sensitive_secret": "حساس: محرمانه"},
        "en": {"pk": "identifier", "fk": "reference", "audit_time": "audit", "audit_user": "audit", "soft_delete": "soft delete",
               "flag": "yes/no", "status": "status", "classifier": "classification", "money": "money", "count": "count",
               "rate": "rate", "time": "time", "payload": "message payload", "external_ref": "external reference",
               "file": "file", "error_info": "error / retry", "identifier": "number / code", "text": "text",
               "geo": "location", "other": "—", "sensitive_national_id": "sensitive: national ID",
               "sensitive_personal": "sensitive: personal", "sensitive_contact": "sensitive: contact",
               "sensitive_financial": "sensitive: financial", "sensitive_secret": "sensitive: secret"}}

T = {
    "fa": {
        "title": "تحلیل بیزنسی Schema `{schema}`",
        "meta_profile": "پروفایل اتصال", "meta_fingerprint": "اثرانگشت متادیتا", "meta_method": "روش",
        "method_rules": "قواعد آفلاین (نام‌ها، کلیدها، روابط، نوع داده و توضیحات ثبت‌شده)",
        "method_ai": "قواعد آفلاین + غنی‌سازی با هوش مصنوعی ({model})",
        "meta_source": "منبع", "source": "فقط ساختار دیتابیس؛ هیچ ردیفی از جدول‌ها خوانده نشده است.",
        "warning": "همه موارد این سند **برداشت بیزنسی** است: از نام‌گذاری، روابط و ساختار استنباط شده و باید با صاحبان فرایند و تیم فنی تأیید شود. مبنای هر برداشت داخل کروشه آمده است ({bases}).",
        "s_summary": "خلاصه مدیریتی", "s_map": "نقشه ماژول‌ها", "s_modules": "ماژول‌های بیزنسی",
        "s_processes": "فرایندهای بیزنسی", "s_entities": "شرح موجودیت‌ها", "s_sensitive": "داده‌های حساس",
        "s_quality": "روابط ضمنی و کیفیت نام‌گذاری", "s_glossary": "واژه‌نامه", "s_questions": "پرسش‌های بیزنسی برای تأیید",
        "sum_counts": "این schema شامل {tables} جدول در {modules} ماژول بیزنسی است؛ {processes} فرایند/الگوی بیزنسی شناسایی شد.",
        "sum_modules": "ماژول‌های اصلی: {items}.", "sum_sensitive": "{n} ستون حاوی داده حساس شناسایی شد.",
        "sum_implicit": "{n} رابطه ضمنی (بدون کلید خارجی) از روی نام ستون‌ها پیدا شد.",
        "sum_quality": "{n} مورد احتمال غلط املایی یا ناهماهنگی در نام‌گذاری دیده شد.",
        "roles_head": ("نقش جدول", "تعداد"),
        "map_note": "هر جعبه یک ماژول و عدد داخل آن تعداد جدول‌هاست؛ پیکان‌ها ارجاع بین ماژول‌ها (کلید خارجی یا رابطه ضمنی) و عدد روی آن‌ها تعداد ارجاع است.",
        "map_rest": "سایر ماژول‌ها: {n} ماژول، {t} جدول",
        "mod_shared": "مشترک (زیرساخت)", "mod_loose": "{name}",
        "mod_desc": "{n} جدول؛ موجودیت محوری: {main}. نقش‌ها: {roles}.",
        "mod_desc_shared": "جدول‌هایی که چند ماژول به آن‌ها ارجاع می‌دهند: {tables}.",
        "mod_links": "ارتباط با ماژول‌های دیگر: {items}.",
        "mod_head": ("جدول", "نام بیزنسی", "نقش", "شرح کوتاه"),
        "proc_ingest": "**دریافت و ثبت {core}:** {steps}",
        "ingest_staging": "داده ابتدا در {t} بارگذاری می‌شود", "ingest_core": "سپس در {t} ثبت می‌شود",
        "ingest_reject": "رکوردهای ردشده در {t} نگه داشته می‌شوند", "ingest_checkpoint": "پیشرفت هر بازه دریافت در {t} ثبت می‌شود",
        "proc_reconcile": "**تطبیق و مغایرت‌گیری — {table}:** نتیجه تطبیق در هر بازه برای {targets} ثبت می‌شود (تعداد تطبیق‌یافته/تطبیق‌نیافته و وضعیت).",
        "proc_matching": "**تطبیق رکوردها:** ستون‌های MATCHED_* در {tables} نشان می‌دهد رکوردهای این جدول‌ها با هم جفت (تطبیق) می‌شوند.",
        "proc_outbox": "**صف ارسال — {table}:** پیام‌ها/کارها در صف قرار می‌گیرند، با تلاش مجدد و ثبت خطا ارسال می‌شوند{src}.",
        "outbox_src": "؛ منشأ آن‌ها {t} است",
        "proc_integration": "**ارتباط با سرویس خارجی — {table}:** درخواست‌ها و پاسخ‌های سرویس بیرونی ثبت و از {users} به آن ارجاع داده می‌شود.",
        "proc_file_import": "**بارگذاری فایل — {table}:** فایل‌ها بارگذاری و نتیجه پردازش ثبت می‌شود{users}.",
        "file_users": "؛ رکوردهای {t} از آن ساخته می‌شوند",
        "proc_access": "**کاربران و سطح دسترسی:** {tables}.", "proc_audit": "**ثبت سابقه تغییرات (ممیزی):** {tables}.",
        "proc_master_detail": "**اصلی و جزئیات:** هر {parent} چند {child} دارد.",
        "life_head": ("جدول", "ستون وضعیت", "مقادیر مجاز در دیتابیس"), "life_title": "چرخه وضعیت (Lifecycle)",
        "life_none": "تعریف نشده", "ai_processes": "فرایندهای پیشنهادی هوش مصنوعی",
        "ent_role": "نقش", "ent_module": "ماژول", "ent_relations": "روابط", "ent_columns": "معنی بیزنسی ستون‌ها",
        "col_head": ("ستون", "معنی بیزنسی", "دسته"),
        "role_staging": "داده‌ها پیش از ثبت نهایی{base} موقتاً اینجا بارگذاری می‌شوند.",
        "role_reject_log": "رکوردهایی که{base} پذیرفته نشده‌اند اینجا ثبت می‌شوند تا بررسی شوند.",
        "role_audit_log": "تغییرات یا رویدادها برای پیگیری و ممیزی اینجا ثبت می‌شوند.",
        "role_outbox": "کارهایی که باید ارسال/پردازش شوند در صف قرار می‌گیرند{cols}.",
        "role_checkpoint": "پیشرفت دریافت/پردازش دوره‌ای{base} برای هر بازه زمانی ثبت می‌شود.",
        "role_reconciliation": "نتیجه تطبیق و مغایرت‌گیری{targets} نگه داشته می‌شود.",
        "role_integration_log": "درخواست‌ها و پاسخ‌های ردوبدل‌شده با سرویس(های) خارجی ثبت می‌شود{cols}.",
        "role_file_import": "فایل‌های بارگذاری‌شده و نتیجه پردازش آن‌ها ثبت می‌شود.",
        "role_junction": "ارتباط چند-به-چند میان {targets} را برقرار می‌کند.",
        "role_lookup": "فهرست مقادیر پایه که {users} به آن ارجاع می‌دهند.",
        "role_security": "اطلاعات کاربران، سطح دسترسی یا مجوزها را نگه می‌دارد.",
        "role_settings": "پارامترها و تنظیمات سیستم را نگه می‌دارد.",
        "role_detail": "سطرهای جزئیات {parent} را نگه می‌دارد؛ هر {parent} می‌تواند چند سطر داشته باشد.",
        "role_transaction": "هر ردیف یک رویداد/تراکنش «{name}» است{money}.",
        "role_master": "موجودیت اصلی «{name}»{n}.", "role_other": "کاربرد این جدول از ساختار و نام آن قطعی نیست.",
        "in_base": " در {t}", "of_base": " از {t}", "for_targets": " برای {t}", "with_cols": " ({cols})",
        "money_part": " و مبلغ آن در {cols} ثبت می‌شود", "n_part": " که {n} جدول دیگر به آن ارجاع می‌دهند",
        "st_comment": "توضیح ثبت‌شده در دیتابیس: «{text}»", "st_copy_of": "ساختار آن تقریباً با {other} یکسان است (احتمالاً کپی یا نسخه موقت).",
        "st_money": "مقادیر مالی: {cols}.", "st_period": "بازه زمانی/اعتبار: {cols}.", "st_status": "وضعیت هر ردیف در {cols} نگهداری می‌شود.",
        "st_external_ref": "شناسه‌های پیگیری در سیستم‌های بیرونی: {cols}.", "st_file": "مسیر یا محتوای فایل: {cols}.",
        "st_audit": "زمان و کاربر ایجاد/تغییر ثبت می‌شود (ممیزی): {cols}.", "st_soft_delete": "حذف به‌صورت منطقی انجام می‌شود: {cols}.",
        "st_sensitive": "شامل داده حساس: {cols}.",
        "rel_many_to_one": "هر {src} به یک {tgt} تعلق دارد{opt}؛ هر {tgt} می‌تواند چند {src} داشته باشد ({cols}).",
        "rel_one_to_one": "هر {src} حداکثر با یک {tgt} مرتبط است{opt} ({cols}).",
        "rel_implicit": "ارتباط ضمنی بدون کلید خارجی: {src} از طریق {cols} احتمالاً به {tgt} اشاره می‌کند.",
        "optional": " (اختیاری)", "referenced_by": "ارجاع‌دهندگان: {tables}.",
        "col_pk": "شناسه یکتای هر ردیف", "col_fk": "ارجاع به {target}", "col_audit_time": "زمان {what}",
        "col_audit_user": "کاربر {what}", "col_soft_delete": "نشانه حذف منطقی", "col_flag": "آیا {subject}؟",
        "what_create": "ایجاد", "what_modify": "آخرین تغییر", "what_delete": "حذف", "values": " — مقادیر: {values}",
        "sens_head": ("جدول", "ستون", "نوع"), "sens_note": "این ستون‌ها در گزارش‌ها، خروجی‌ها و دسترسی کاربران نیاز به کنترل یا پوشاندن دارند.",
        "sens_none": "ستون حساسی از روی نام‌ها شناسایی نشد.",
        "imp_title": "روابط ضمنی (بدون کلید خارجی)", "imp_head": ("جدول", "ستون", "احتمالاً ارجاع به"),
        "imp_note": "این روابط در دیتابیس تعریف نشده‌اند؛ تعریف کلید خارجی برای آن‌ها یکپارچگی داده را تضمین می‌کند.",
        "typo_title": "احتمال غلط املایی در نام‌ها", "typo_head": ("واژه", "پیشنهاد", "محل"),
        "mismatch_title": "ناهماهنگی املای ستون و جدول مقصد",
        "q_spelling_mismatch": "ستون {column} در {table} به {target} اشاره می‌کند ولی املای آن متفاوت است.",
        "quality_none": "مورد قابل توجهی دیده نشد.",
        "glo_head": ("واژه در نام‌ها", "معادل فارسی", "تکرار"), "glo_unknown": "واژه‌های ناشناخته (نیاز به تعریف): {terms}",
        "q_unknown_terms": "معنی این واژه‌ها/اختصارها در نام‌گذاری چیست؟ {terms}",
        "q_unclear_table": "کاربرد بیزنسی جدول {table} چیست؟",
        "q_status_values": "مقادیر مجاز و معنی ستون {column} در {table} چیست؟ (در دیتابیس محدودیتی تعریف نشده)",
        "ai_label": "هوش مصنوعی", "ai_summary": "جمع‌بندی هوش مصنوعی", "ai_domain": "حوزه کسب‌وکار (برداشت)",
        "coverage": "پوشش: {n} از {total} جدول در این سند شرح داده شده است.",
        "list_sep": "، ", "and_more": " و {n} مورد دیگر",
    },
    "en": {
        "title": "Business analysis of schema `{schema}`",
        "meta_profile": "Connection profile", "meta_fingerprint": "Metadata fingerprint", "meta_method": "Method",
        "method_rules": "Offline rules (names, keys, relationships, data types and recorded comments)",
        "method_ai": "Offline rules + AI enrichment ({model})",
        "meta_source": "Source", "source": "Database structure only; no table rows were read.",
        "warning": "Everything in this document is a **business inference** drawn from naming, relationships and structure; confirm it with the process owners and the technical team. The basis of each inference is shown in brackets ({bases}).",
        "s_summary": "Executive summary", "s_map": "Module map", "s_modules": "Business modules",
        "s_processes": "Business processes", "s_entities": "Entities", "s_sensitive": "Sensitive data",
        "s_quality": "Implicit relationships and naming quality", "s_glossary": "Glossary", "s_questions": "Business questions to confirm",
        "sum_counts": "The schema has {tables} tables in {modules} business modules; {processes} business processes/patterns were recognised.",
        "sum_modules": "Main modules: {items}.", "sum_sensitive": "{n} columns hold sensitive data.",
        "sum_implicit": "{n} implicit relationships (no foreign key) were found from column names.",
        "sum_quality": "{n} likely misspellings or naming inconsistencies were found.",
        "roles_head": ("Table role", "Count"),
        "map_note": "Each box is a module with its table count; arrows are references between modules (foreign keys or implicit links) with their count.",
        "map_rest": "Other modules: {n} modules, {t} tables",
        "mod_shared": "Shared (infrastructure)", "mod_loose": "{name}",
        "mod_desc": "{n} tables; central entity: {main}. Roles: {roles}.",
        "mod_desc_shared": "Tables referenced from several modules: {tables}.",
        "mod_links": "Links to other modules: {items}.",
        "mod_head": ("Table", "Business name", "Role", "Summary"),
        "proc_ingest": "**Fetching and recording {core}:** {steps}",
        "ingest_staging": "rows are first loaded into {t}", "ingest_core": "then stored in {t}",
        "ingest_reject": "rejected rows are kept in {t}", "ingest_checkpoint": "progress per fetch range is recorded in {t}",
        "proc_reconcile": "**Reconciliation — {table}:** the result of matching per range is recorded for {targets} (matched/unmatched counts and status).",
        "proc_matching": "**Record matching:** MATCHED_* columns in {tables} show that their rows are paired (matched) with each other.",
        "proc_outbox": "**Outbox — {table}:** messages/jobs are queued and sent with retries and error tracking{src}.",
        "outbox_src": "; they originate from {t}",
        "proc_integration": "**External-service exchange — {table}:** requests to and responses from an outside service are logged; {users} reference it.",
        "proc_file_import": "**File import — {table}:** files are uploaded and their processing result is recorded{users}.",
        "file_users": "; {t} rows are created from them",
        "proc_access": "**Users and access levels:** {tables}.", "proc_audit": "**Change history (audit):** {tables}.",
        "proc_master_detail": "**Master and detail:** each {parent} has several {child}.",
        "life_head": ("Table", "Status column", "Allowed values in the database"), "life_title": "Status lifecycles",
        "life_none": "not defined", "ai_processes": "Processes suggested by AI",
        "ent_role": "Role", "ent_module": "Module", "ent_relations": "Relationships", "ent_columns": "Business meaning of columns",
        "col_head": ("Column", "Business meaning", "Category"),
        "role_staging": "Rows are loaded here temporarily before being stored{base}.",
        "role_reject_log": "Rows that were not accepted{base} are recorded here for review.",
        "role_audit_log": "Changes or events are recorded here for tracking and audit.",
        "role_outbox": "Work to be sent/processed is queued here{cols}.",
        "role_checkpoint": "Progress of the periodic fetch/processing{base} is recorded per time range.",
        "role_reconciliation": "Holds the result of reconciliation{targets}.",
        "role_integration_log": "Requests and responses exchanged with outside services are logged{cols}.",
        "role_file_import": "Uploaded files and the result of processing them are recorded.",
        "role_junction": "Links {targets} many-to-many.",
        "role_lookup": "List of reference values used by {users}.",
        "role_security": "Holds users, access levels or permissions.",
        "role_settings": "Holds system parameters and settings.",
        "role_detail": "Holds the detail rows of {parent}; each {parent} can have several rows.",
        "role_transaction": "Each row is a «{name}» event/transaction{money}.",
        "role_master": "Core «{name}» entity{n}.", "role_other": "The purpose of this table is not clear from its structure and name.",
        "in_base": " in {t}", "of_base": " of {t}", "for_targets": " for {t}", "with_cols": " ({cols})",
        "money_part": "; its amount is in {cols}", "n_part": ", referenced by {n} other tables",
        "st_comment": "Recorded comment: «{text}»", "st_copy_of": "Its structure nearly matches {other} (likely a copy or temporary version).",
        "st_money": "Money values: {cols}.", "st_period": "Time range / validity: {cols}.", "st_status": "Row status is kept in {cols}.",
        "st_external_ref": "Tracking identifiers in outside systems: {cols}.", "st_file": "File path or content: {cols}.",
        "st_audit": "Creation/change time and user are recorded (audit): {cols}.", "st_soft_delete": "Rows are deleted logically: {cols}.",
        "st_sensitive": "Holds sensitive data: {cols}.",
        "rel_many_to_one": "Each {src} belongs to one {tgt}{opt}; a {tgt} can have many {src} ({cols}).",
        "rel_one_to_one": "Each {src} relates to at most one {tgt}{opt} ({cols}).",
        "rel_implicit": "Implicit link without a foreign key: {src} probably points to {tgt} through {cols}.",
        "optional": " (optional)", "referenced_by": "Referenced by: {tables}.",
        "col_pk": "Unique identifier of each row", "col_fk": "Reference to {target}", "col_audit_time": "Time of {what}",
        "col_audit_user": "User who did the {what}", "col_soft_delete": "Logical-delete marker", "col_flag": "Whether {subject}",
        "what_create": "creation", "what_modify": "last change", "what_delete": "deletion", "values": " — values: {values}",
        "sens_head": ("Table", "Column", "Kind"), "sens_note": "These columns need access control or masking in reports, exports and user access.",
        "sens_none": "No sensitive columns were recognised from names.",
        "imp_title": "Implicit relationships (no foreign key)", "imp_head": ("Table", "Column", "Probably references"),
        "imp_note": "These relationships are not declared in the database; a foreign key would guarantee their integrity.",
        "typo_title": "Likely misspellings in names", "typo_head": ("Word", "Suggestion", "Where"),
        "mismatch_title": "Column and target table spelled differently",
        "q_spelling_mismatch": "Column {column} in {table} references {target} but is spelled differently.",
        "quality_none": "Nothing notable was found.",
        "glo_head": ("Word in names", "Meaning", "Count"), "glo_unknown": "Unknown words (need a definition): {terms}",
        "q_unknown_terms": "What do these words/abbreviations in the names mean? {terms}",
        "q_unclear_table": "What is the business purpose of table {table}?",
        "q_status_values": "What are the allowed values and meaning of {column} in {table}? (no constraint in the database)",
        "ai_label": "AI", "ai_summary": "AI summary", "ai_domain": "Business domain (inferred)",
        "coverage": "Coverage: {n} of {total} tables are described in this document.",
        "list_sep": ", ", "and_more": " and {n} more",
    },
}


MAP_MAX = 25  # module-map boxes; smaller modules are drawn as one "other modules" box


class _Doc:
    def __init__(self, lang):
        self.lang, self.s, self.lines, self.n = lang, T[lang], [], 0

    def w(self, line=""):
        self.lines.append(line)

    def num(self, v):
        return str(v).translate(FA_DIGITS) if self.lang == "fa" else str(v)

    def h2(self, key):
        self.n += 1
        self.w(f"## {self.num(self.n)}. {self.s[key]}")
        self.w()

    def join(self, items, limit=None):
        items = list(items)
        more = ""
        if limit and len(items) > limit:
            more = self.s["and_more"].format(n=self.num(len(items) - limit))
            items = items[:limit]
        return self.s["list_sep"].join(items) + more

    def table(self, head, rows):
        self.w("| " + " | ".join(head) + " |")
        self.w("|" + "---|" * len(head))
        for r in rows:
            self.w("| " + " | ".join(cell(x) if not str(x).startswith("`") else str(x) for x in r) + " |")
        self.w()


def render_business(snap, biz, *, lang="fa", ai=None):
    """Markdown for the business analysis plus a coverage dict."""
    d = _Doc(lang)
    s = d.s
    ai = ai or {}
    ai_tables, ai_modules = ai.get("tables") or {}, ai.get("modules") or {}

    def bname(t):
        return (ai_tables.get(t) or {}).get("business_name") or name_phrase(t, lang)

    def tn(t):
        return f"«{bname(t)}» (`{t}`)" if lang == "fa" else f"{bname(t)} (`{t}`)"

    def tns(ts, limit=8):
        return d.join((tn(t) for t in ts), limit)

    def cols(cs, limit=6):
        return d.join((f"`{c}`" for c in cs), limit)

    def basis(b):
        return " [" + d.s["list_sep"].join(BASIS[lang][x] for x in b) + "]"

    def mname(m):
        if m["shared"]:
            return s["mod_shared"]
        return (ai_modules.get(m["key"]) or {}).get("name") or phrase([m["token"]], lang) or m["token"]

    tables = biz["tables"]
    emitted_modules, emitted_entities = set(), set()

    # ---- header ----
    d.w(f"# {s['title'].format(schema=snap['schema'])}")
    d.w()
    d.w(f"- **{s['meta_profile']}:** `{snap['profile']}`")
    d.w(f"- **{s['meta_fingerprint']}:** `{snap['fingerprint']}`")
    method = s["method_ai"].format(model=ai["model"]) if ai.get("model") else s["method_rules"]
    d.w(f"- **{s['meta_method']}:** {method}")
    d.w(f"- **{s['meta_source']}:** {s['source']}")
    d.w()
    d.w("> " + s["warning"].format(bases=d.s["list_sep"].join(BASIS[lang].values())))
    d.w()

    # ---- 1. summary ----
    d.h2("s_summary")
    if ai.get("domain"):
        d.w(f"**{s['ai_domain']}:** {ai['domain']} [{BASIS[lang]['ai']}]")
        d.w()
    if ai.get("summary"):
        d.w(f"{ai['summary']} [{BASIS[lang]['ai']}]")
        d.w()
    sm = biz["summary"]
    d.w("- " + s["sum_counts"].format(tables=d.num(sm["tables"]), modules=d.num(sm["modules"]),
                                     processes=d.num(len(biz["processes"]))))
    top = [m for m in biz["modules"] if not m["shared"]][:6]
    d.w("- " + s["sum_modules"].format(items=d.join(f"{mname(m)} ({d.num(len(m['tables']))})" for m in top)))
    if sm["sensitive"]:
        d.w("- " + s["sum_sensitive"].format(n=d.num(sm["sensitive"])))
    if sm["implicit"]:
        d.w("- " + s["sum_implicit"].format(n=d.num(sm["implicit"])))
    nq = sum(1 for q in biz["quality"] if q["code"] in ("q_typo", "q_spelling_mismatch"))
    if nq:
        d.w("- " + s["sum_quality"].format(n=d.num(nq)))
    d.w()
    d.table(s["roles_head"], [(ROLE[lang][r], d.num(n)) for r, n in sorted(sm["roles"].items(), key=lambda kv: -kv[1])])

    # ---- 2. module map ----
    d.h2("s_map")
    d.w(s["map_note"])
    d.w()
    d.w("```mermaid")
    d.w("flowchart LR")
    shown = biz["modules"] if len(biz["modules"]) <= MAP_MAX else biz["modules"][:MAP_MAX - 1]
    rest = biz["modules"][len(shown):]
    ids = {m["key"]: f"M{i + 1}" for i, m in enumerate(shown)}
    ids.update({m["key"]: "MX" for m in rest})
    for m in shown:
        label = f"{mname(m)} ({len(m['tables'])})".replace('"', "'")
        d.w(f'    {ids[m["key"]]}["{label}"]')
    if rest:
        label = s["map_rest"].format(n=len(rest), t=sum(len(m["tables"]) for m in rest))
        d.w(f'    MX["{label}"]')
    edges = {}
    for m in biz["modules"]:
        for other, n in m["links"]:
            a, b = ids[m["key"]], ids[other]
            if a != b:
                edges[(a, b)] = edges.get((a, b), 0) + n
    for (a, b), n in sorted(edges.items(), key=lambda kv: (int(kv[0][0][1:]) if kv[0][0] != "MX" else 10**6,
                                                           kv[0][1])):
        d.w(f"    {a} -->|{n}| {b}")
    d.w("```")
    d.w()

    # ---- 3. modules ----
    d.h2("s_modules")
    for m in biz["modules"]:
        d.w(f"### {mname(m)}")
        d.w()
        aim = ai_modules.get(m["key"]) or {}
        if aim.get("description"):
            d.w(f"{aim['description']} [{BASIS[lang]['ai']}]")
            d.w()
        if m["shared"]:
            d.w(s["mod_desc_shared"].format(tables=tns(m["tables"])))
        else:
            roles = d.join(f"{ROLE[lang][r]} ({d.num(n)})" for r, n in sorted(m["roles"].items(), key=lambda kv: -kv[1]))
            d.w(s["mod_desc"].format(n=d.num(len(m["tables"])), main=tn(m["main"]), roles=roles))
        if m["links"]:
            names = {x["key"]: mname(x) for x in biz["modules"]}
            d.w()
            d.w(s["mod_links"].format(items=d.join(f"{names[k]} ({d.num(n)})" for k, n in m["links"])))
        d.w()
        rows = []
        for t in m["tables"]:
            b = tables[t]
            short = (ai_tables.get(t) or {}).get("description") or _statement(d, b["statements"][1] if b["comment"]
                                                                           else b["statements"][0], tn, tns, cols, lang)
            rows.append((f"`{t}`", bname(t), ROLE[lang][b["role"]], _first_sentence(short)))
            emitted_modules.add(t)
        d.table(s["mod_head"], rows)

    # ---- 4. processes ----
    d.h2("s_processes")
    procs = [p for p in biz["processes"] if p["code"] != "proc_lifecycle"]
    for i, p in enumerate(procs, start=1):
        d.w(f"{d.num(i)}. {_process(d, p, tn, tns, cols)}{basis(p['basis'])}")
    if procs:
        d.w()
    for i, p in enumerate(ai.get("processes") or [], start=1):
        if i == 1:
            d.w(f"**{s['ai_processes']}** [{BASIS[lang]['ai']}]")
            d.w()
        known = [t for t in p.get("tables") or [] if t in tables]
        d.w(f"- **{p['name']}:** {p['description']}" + (f" ({tns(known)})" if known else ""))
    if ai.get("processes"):
        d.w()
    life = [p for p in biz["processes"] if p["code"] == "proc_lifecycle"]
    if life:
        d.w(f"### {s['life_title']}")
        d.w()
        d.table(s["life_head"], [(f"`{p['params']['table']}`", f"`{p['params']['column']}`",
                                  d.join(p["params"]["values"]) if p["params"]["values"] else s["life_none"])
                                 for p in life])

    # ---- 5. entities ----
    d.h2("s_entities")
    mod_of = {t: mname(m) for m in biz["modules"] for t in m["tables"]}
    for t in sorted(tables):
        b = tables[t]
        emitted_entities.add(t)
        d.w(f"### `{t}` — {bname(t)}")
        d.w()
        d.w(f"- **{s['ent_role']}:** {ROLE[lang][b['role']]} — **{s['ent_module']}:** {mod_of.get(t, '—')}")
        aitab = ai_tables.get(t) or {}
        if aitab.get("description"):
            d.w(f"- {aitab['description']} [{BASIS[lang]['ai']}]")
        for st in b["statements"]:
            d.w(f"- {_statement(d, st, tn, tns, cols, lang)}{basis(st['basis'])}")
        if b["relations"] or b["in"]:
            d.w(f"- **{s['ent_relations']}:**")
            for r in b["relations"]:
                d.w(f"  - {_relation(d, r, tn, cols)}{basis(r['basis'])}")
            refs = sorted({x[0] for x in b["in"]})
            if refs:
                d.w(f"  - {s['referenced_by'].format(tables=tns(refs))}")
        d.w()
        d.w(f"**{s['ent_columns']}:**")
        d.w()
        ai_cols = aitab.get("columns") or {}
        rows = []
        for c in b["columns"]:
            meaning = ai_cols.get(c["column"])
            meaning = f"{meaning} ({BASIS[lang]['ai']})" if meaning else _column_meaning(d, c, tn, lang)
            rows.append((f"`{c['column']}`", meaning, KIND[lang].get(c["kind"], c["kind"])))
        d.table(s["col_head"], rows)

    # ---- 6. sensitive ----
    d.h2("s_sensitive")
    if biz["sensitive"]:
        d.w(s["sens_note"])
        d.w()
        d.table(s["sens_head"], [(f"`{x['table']}`", f"`{x['column']}`", KIND[lang][f"sensitive_{x['kind']}"])
                                 for x in biz["sensitive"]])
    else:
        d.w(s["sens_none"])
        d.w()

    # ---- 7. quality ----
    d.h2("s_quality")
    imp = biz["implicit_relations"]
    typos = [q for q in biz["quality"] if q["code"] == "q_typo"]
    mism = [q for q in biz["quality"] if q["code"] == "q_spelling_mismatch"]
    if imp:
        d.w(f"### {s['imp_title']}")
        d.w()
        d.w(s["imp_note"])
        d.w()
        d.table(s["imp_head"], [(f"`{i['table']}`", f"`{i['column']}`", f"`{i['target']}`") for i in imp])
    if typos:
        d.w(f"### {s['typo_title']}")
        d.w()
        d.table(s["typo_head"], [(f"`{q['params']['token']}`", " / ".join(q["params"]["suggest"]),
                                  d.join((f"`{w}`" for w in q["params"]["where"]), 4)) for q in typos])
    if mism:
        d.w(f"### {s['mismatch_title']}")
        d.w()
        for q in mism:
            p = q["params"]
            d.w("- " + s["q_spelling_mismatch"].format(column=f"`{p['column']}`", table=f"`{p['table']}`",
                                                       target=f"`{p['target']}`"))
        d.w()
    if not (imp or typos or mism):
        d.w(s["quality_none"])
        d.w()

    # ---- 8. glossary ----
    d.h2("s_glossary")
    known = [g for g in biz["glossary"] if g["known"]][:80]
    d.table(s["glo_head"], [(f"`{g['term'].upper()}`", VOCAB[g["term"]][0 if lang == "fa" else 1], d.num(g["count"]))
                            for g in known])
    unknown = [g["term"].upper() for g in biz["glossary"] if not g["known"]]
    if unknown:
        d.w(s["glo_unknown"].format(terms=d.join((f"`{u}`" for u in unknown), 40)))
        d.w()

    # ---- 9. questions ----
    d.h2("s_questions")
    qs = []
    for q in biz["questions"]:
        p = q["params"]
        if q["code"] == "q_unknown_terms":
            qs.append(s["q_unknown_terms"].format(terms=d.join(f"`{x}`" for x in p["terms"])))
        elif q["code"] == "q_unclear_table":
            qs.append(s["q_unclear_table"].format(table=tn(p["table"])))
        else:
            qs.append(s["q_status_values"].format(column=f"`{p['column']}`", table=tn(p["table"])))
    qs += [f"{x} [{BASIS[lang]['ai']}]" for x in ai.get("questions") or []]
    for i, q in enumerate(qs, start=1):
        d.w(f"{d.num(i)}. {q}")
    d.w()

    all_tables = set(tables)
    coverage = {
        "tables": len(all_tables), "in_modules": len(emitted_modules & all_tables),
        "in_entities": len(emitted_entities & all_tables),
        "missing": sorted(all_tables - (emitted_modules & emitted_entities)),
    }
    coverage["passed"] = not coverage["missing"]
    d.w("---")
    d.w()
    d.w(s["coverage"].format(n=d.num(len(emitted_modules & emitted_entities)), total=d.num(len(all_tables))))
    d.w()
    return "\n".join(d.lines).rstrip("\n") + "\n", coverage


def _first_sentence(text):
    text = " ".join(str(text).split())
    for sep in (". ", "؛ ", "; "):
        if sep in text:
            return text.split(sep)[0] + ("." if sep == ". " else "")
    return text


def _statement(d, st, tn, tns, cols, lang):
    s, p = d.s, st["params"]
    code_ = st["code"]
    if code_.startswith("role_"):
        role = code_[5:]
        extra = {}
        if role in ("staging", "checkpoint"):
            extra["base"] = (s["in_base"] if role == "staging" else s["of_base"]).format(t=tn(p["base"])) if p.get("base") else ""
        if role == "reject_log":
            extra["base"] = s["in_base"].format(t=tn(p["base"])) if p.get("base") else ""
        if role in ("outbox", "integration_log"):
            extra["cols"] = s["with_cols"].format(cols=cols(p["cols"])) if p.get("cols") else ""
        if role == "reconciliation":
            extra["targets"] = s["for_targets"].format(t=tns(p["targets"])) if p.get("targets") else ""
        if role == "junction":
            extra["targets"] = tns(p["targets"])
        if role == "lookup":
            extra["users"] = tns(p["users"]) if p.get("users") else "—"
        if role == "detail":
            extra["parent"] = tn(p["parent"])
        if role == "transaction":
            extra["name"] = name_phrase(p["name"], lang)
            extra["money"] = s["money_part"].format(cols=cols(p["money"])) if p.get("money") else ""
        if role == "master":
            extra["name"] = name_phrase(p["name"], lang)
            extra["n"] = s["n_part"].format(n=d.num(p["n"])) if p.get("n") else ""
        return s[code_].format(**extra)
    if code_ == "st_comment":
        return s[code_].format(text=" ".join(p["text"].split()))
    if code_ == "st_copy_of":
        return s[code_].format(other=tn(p["other"]))
    return s[code_].format(cols=cols(p["cols"]))


def _process(d, p, tn, tns, cols):
    s, a, c = d.s, p["params"], p["code"]
    if c == "proc_ingest":
        steps = [s["ingest_staging"].format(t=tn(a["staging"])) if a.get("staging") else None,
                 s["ingest_core"].format(t=tn(a["core"])) if a.get("core") else None,
                 s["ingest_reject"].format(t=tn(a["reject"])) if a.get("reject") else None,
                 s["ingest_checkpoint"].format(t=tn(a["checkpoint"])) if a.get("checkpoint") else None]
        core = tn(a["core"]) if a.get("core") else tns(p["tables"])
        return s[c].format(core=core, steps=s["list_sep"].join(x for x in steps if x) + ".")
    if c == "proc_reconcile":
        return s[c].format(table=tn(a["table"]), targets=tns(a["targets"]) if a["targets"] else "—")
    if c in ("proc_matching", "proc_access", "proc_audit"):
        return s[c].format(tables=tns(a["tables"]))
    if c == "proc_outbox":
        src = s["outbox_src"].format(t=tns(a["sources"])) if a["sources"] else ""
        return s[c].format(table=tn(a["table"]), src=src)
    if c == "proc_integration":
        return s[c].format(table=tn(a["table"]), users=tns(a["users"]) if a["users"] else "—")
    if c == "proc_file_import":
        users = s["file_users"].format(t=tns(a["users"])) if a["users"] else ""
        return s[c].format(table=tn(a["table"]), users=users)
    if c == "proc_master_detail":
        return s[c].format(parent=tn(a["parent"]), child=tn(a["child"]))
    return c


def _relation(d, r, tn, cols):
    s, p = d.s, r["params"]
    return s[r["code"]].format(src=tn(p["src"]), tgt=tn(p["tgt"]), cols=cols(p["cols"]),
                               opt=s["optional"] if p.get("optional") else "")


def _column_meaning(d, c, tn, lang):
    s, k, p = d.s, c["kind"], c["params"]
    toks = c["tokens"]
    if k == "pk":
        return s["col_pk"]
    if k == "fk":
        return s["col_fk"].format(target=tn(p["target"])) + (" *" if c.get("implicit") else "")
    if k in ("audit_time", "audit_user"):
        return s[f"col_{k}"].format(what=s[f"what_{p['what']}"])
    if k == "soft_delete":
        return s["col_soft_delete"]
    if k == "flag":
        subject = phrase(p["subject"], lang) or phrase(toks, lang)
        return s["col_flag"].format(subject=subject)
    text = phrase([t for t in toks if t != "id"] or toks, lang)
    if k in ("status", "classifier") and p.get("values"):
        text += s["values"].format(values=d.join(p["values"]))
    return text


def business_names(schema, lang):
    return {"markdown": f"{schema}_Business_Analysis.{lang}.md", "ai": f"{schema}_business_ai.{lang}.json"}
