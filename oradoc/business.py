"""Business analysis of a snapshot, offline and rule based.

Unlike analysis.py (which never infers from a name alone), this module deliberately reads table and
column NAMES together with keys, relationships and data types to guess the business meaning of a
schema. Everything it produces is a «برداشت بیزنسی» (business inference) to be confirmed by the
process owners; each statement carries the basis it rests on (name / relationship / type / comment).

Output (pure function of the snapshot, so it is reproducible):
  {"tables": {T: {...}}, "modules": [...], "processes": [...], "implicit_relations": [...],
   "sensitive": [...], "quality": [...], "glossary": [...], "questions": [...], "summary": {...}}
Statements are template codes + params, rendered in fa or en by business_render.
"""
import difflib
import re
from collections import Counter, defaultdict

from .analysis import analyze

# ---------------------------------------------------------------------------
# Vocabulary: English (and common Finglish) name tokens -> (Persian, English)
# ---------------------------------------------------------------------------

_V = """
account:حساب|Account  accounts:حساب|Account  acc:حساب|Account  ledger:دفتر کل|Ledger  entry:ثبت|Entry
transaction:تراکنش|Transaction  trans:تراکنش|Transaction  txn:تراکنش|Transaction  payment:پرداخت|Payment
pay:پرداخت|Payment  invoice:فاکتور|Invoice  bill:صورت‌حساب|Bill  receipt:رسید|Receipt  voucher:سند حسابداری|Voucher
amount:مبلغ|Amount  amt:مبلغ|Amount  price:قیمت|Price  cost:هزینه|Cost  fee:کارمزد|Fee  rate:نرخ|Rate
balance:مانده|Balance  debit:بدهکار|Debit  credit:بستانکار|Credit  debt:بدهی|Debt  loan:وام|Loan
installment:قسط|Installment  interest:سود|Interest  tax:مالیات|Tax  discount:تخفیف|Discount  salary:حقوق|Salary
wage:دستمزد|Wage  bonus:پاداش|Bonus  budget:بودجه|Budget  currency:ارز|Currency  bank:بانک|Bank
card:کارت|Card  iban:شبا|IBAN  sheba:شبا|IBAN  cheque:چک|Cheque  check:بررسی|Check  wallet:کیف پول|Wallet
topup:شارژ|Top-up  charge:شارژ|Charge  refund:بازپرداخت|Refund  settlement:تسویه|Settlement  deposit:واریز|Deposit
withdraw:برداشت|Withdrawal  withdrawal:برداشت|Withdrawal  transfer:انتقال|Transfer  reconciliation:تطبیق|Reconciliation
reconcile:تطبیق|Reconciliation  variance:مغایرت|Variance  matched:تطبیق‌یافته|Matched  unmatched:تطبیق‌نیافته|Unmatched
merchant:پذیرنده|Merchant  terminal:پایانه|Terminal  pos:کارتخوان|POS  rrn:شماره مرجع بانکی|RRN  stan:شماره پیگیری|STAN
order:سفارش|Order  item:قلم|Item  line:سطر|Line  product:محصول|Product  goods:کالا|Goods  stock:موجودی انبار|Stock
inventory:موجودی|Inventory  warehouse:انبار|Warehouse  supplier:تأمین‌کننده|Supplier  vendor:فروشنده|Vendor
customer:مشتری|Customer  client:مشتری|Client  contract:قرارداد|Contract  agreement:توافق|Agreement  quote:پیش‌فاکتور|Quote
sale:فروش|Sale  sales:فروش|Sales  purchase:خرید|Purchase  shipment:ارسال کالا|Shipment  delivery:تحویل|Delivery
person:شخص|Person  people:اشخاص|People  personnel:پرسنل|Personnel  employee:کارمند|Employee  staff:کارکنان|Staff
member:عضو|Member  user:کاربر|User  users:کاربر|User  role:نقش|Role  permission:مجوز|Permission  access:دسترسی|Access
login:ورود|Login  session:نشست|Session  password:رمز عبور|Password  hash:هش|Hash  token:توکن|Token  level:سطح|Level
group:گروه|Group  team:تیم|Team  department:واحد سازمانی|Department  dept:واحد سازمانی|Department  org:سازمان|Organization
organization:سازمان|Organization  unit:واحد|Unit  branch:شعبه|Branch  company:شرکت|Company  corporation:شرکت|Corporation
cooperation:همکاری|Cooperation  position:سمت|Position  job:شغل|Job  employment:استخدام|Employment  manager:مدیر|Manager
family:خانواده|Family  child:فرزند|Child  children:فرزندان|Children  parent:والد|Parent  spouse:همسر|Spouse
profile:پروفایل|Profile  patient:بیمار|Patient  doctor:پزشک|Doctor  insurance:بیمه|Insurance  policy:بیمه‌نامه|Policy
claim:خسارت|Claim  benefit:مزایا|Benefit  welfare:رفاه|Welfare  pension:مستمری|Pension  assessment:ارزیابی|Assessment
question:پرسش|Question  answer:پاسخ|Answer  option:گزینه|Option  survey:نظرسنجی|Survey  submission:ارسال پاسخ|Submission
interpretation:تفسیر|Interpretation  score:امتیاز|Score  result:نتیجه|Result  exam:آزمون|Exam  course:دوره|Course
student:دانشجو|Student  teacher:مدرس|Teacher  class:کلاس|Class  request:درخواست|Request  response:پاسخ|Response
information:اطلاعات|Information  info:اطلاعات|Information  data:داده|Data  detail:جزئیات|Detail
details:جزئیات|Details  message:پیام|Message  msg:پیام|Message  sms:پیامک|SMS  email:ایمیل|Email  mail:نامه|Mail
notification:اعلان|Notification  outbox:صف ارسال|Outbox  inbox:صندوق دریافت|Inbox  queue:صف|Queue  letter:نامه|Letter
document:سند|Document  doc:سند|Document  file:فایل|File  attachment:پیوست|Attachment  image:تصویر|Image  photo:عکس|Photo
path:مسیر|Path  url:نشانی وب|URL  website:وب‌سایت|Website  extension:پسوند|Extension  import:بارگذاری|Import
export:خروجی|Export  report:گزارش|Report  log:لاگ|Log  logs:لاگ|Log  history:سابقه|History  audit:ممیزی|Audit
trail:ردگیری|Trail  action:اقدام|Action  event:رویداد|Event  activity:فعالیت|Activity  task:وظیفه|Task  job2:کار|Job
process:فرایند|Process  workflow:گردش کار|Workflow  step:مرحله|Step  stage:مرحله|Stage  approval:تأیید|Approval
approve:تأیید|Approve  approved:تأییدشده|Approved  reject:رد|Reject  rejected:ردشده|Rejected  confirm:تأیید|Confirm
status:وضعیت|Status  state:وضعیت|State  type:نوع|Type  kind:نوع|Kind  category:دسته‌بندی|Category  class2:رده|Class
code:کد|Code  number:شماره|Number  num:شماره|Number  no:شماره|Number  id:شناسه|ID  key:کلید|Key  identity:شناسه|Identity
identifier:شناسه|Identifier  reference:مرجع|Reference  ref:مرجع|Reference  tracking:پیگیری|Tracking  serial:سریال|Serial
name:نام|Name  title:عنوان|Title  description:شرح|Description  desc:شرح|Description  note:یادداشت|Note  comment:توضیح|Comment
text:متن|Text  value:مقدار|Value  count:تعداد|Count  cnt:تعداد|Count  qty:تعداد|Quantity  quantity:تعداد|Quantity
total:کل|Total  sum:جمع|Sum  date:تاریخ|Date  time:زمان|Time  datetime:زمان|Date-time  dt:تاریخ|Date  year:سال|Year
month:ماه|Month  day:روز|Day  days:روز|Days  period:دوره|Period  range:بازه|Range  start:شروع|Start  end:پایان|End
begin:شروع|Begin  from:از|From  to:تا|To  expire:انقضا|Expiry  expiry:انقضا|Expiry  due:سررسید|Due  deadline:مهلت|Deadline
gregorian:میلادی|Gregorian  jalali:شمسی|Jalali  shamsi:شمسی|Jalali  created:ایجاد|Creation  create:ایجاد|Creation
modified:تغییر|Modification  updated:به‌روزرسانی|Update  update:به‌روزرسانی|Update  deleted:حذف|Deletion  delete:حذف|Deletion
inserted:درج|Insert  fetched:دریافت|Fetch  sent:ارسال|Sending  send:ارسال|Send  received:دریافت|Receipt  attempt:تلاش|Attempt
retry:تلاش مجدد|Retry  error:خطا|Error  exception:استثنا|Exception  lease:اجاره پردازش|Lease  lock:قفل|Lock
checkpoint:نقطه کنترل|Checkpoint  batch:دسته|Batch  sync:همگام‌سازی|Sync  tmp:موقت|Temp  temp:موقت|Temp
staging:موقت|Staging  backup:پشتیبان|Backup  archive:بایگانی|Archive  copy:کپی|Copy  old:قدیمی|Old  main:اصلی|Main
master:اصلی|Master  primary:اصلی|Primary  secondary:ثانویه|Secondary  original:اصلی|Original  full:کامل|Full
long:بلند|Long  short:کوتاه|Short  active:فعال|Active  activated:فعال‌شده|Activated  enabled:فعال|Enabled
bound:متصل|Bound  resolved:حل‌شده|Resolved  valid:معتبر|Valid  current:جاری|Current  next:بعدی|Next
previous:قبلی|Previous  prev:قبلی|Previous  target:هدف|Target  source:مبدأ|Source  destination:مقصد|Destination
location:محل|Location  address:نشانی|Address  addr:نشانی|Address  city:شهر|City
province:استان|Province  state2:ایالت|State  country:کشور|Country  region:منطقه|Region  zone:ناحیه|Zone
postal:پستی|Postal  zip:کد پستی|ZIP  phone:تلفن|Phone  tel:تلفن|Phone  mobile:موبایل|Mobile  fax:نمابر|Fax
lat:عرض جغرافیایی|Latitude  latitude:عرض جغرافیایی|Latitude  lng:طول جغرافیایی|Longitude  lon:طول جغرافیایی|Longitude
longitude:طول جغرافیایی|Longitude  national:ملی|National  passport:گذرنامه|Passport  birth:تولد|Birth
gender:جنسیت|Gender  sex:جنسیت|Sex  father:پدر|Father  mother:مادر|Mother  first:نخست|First  last:آخرین|Last
family2:خانوادگی|Family  age:سن|Age  marital:تأهل|Marital  education:تحصیلات|Education  nationality:تابعیت|Nationality
username:نام کاربری|Username  setting:تنظیم|Setting  settings:تنظیمات|Settings  config:پیکربندی|Configuration
configuration:پیکربندی|Configuration  parameter:پارامتر|Parameter  param:پارامتر|Parameter  lookup:مرجع|Lookup
json:JSON|JSON  xml:XML|XML  payload:محتوای پیام|Payload  script:اسکریپت|Script  table:جدول|Table  field:فیلد|Field
column:ستون|Column  old2:قبلی|Old  new:جدید|New  keyvalue:مقدار کلید|Key value  oldvalue:مقدار قبلی|Old value
newvalue:مقدار جدید|New value  idempotency:عدم تکرار|Idempotency  unique:یکتا|Unique  uuid:شناسه یکتا|UUID  guid:شناسه یکتا|GUID
version:نسخه|Version  sort:ترتیب|Sort  seq:ترتیب|Sequence  sequence:ترتیب|Sequence  priority:اولویت|Priority
max:حداکثر|Maximum  min:حداقل|Minimum  limit:سقف|Limit  threshold:آستانه|Threshold  remaining:باقی‌مانده|Remaining
percent:درصد|Percent  percentage:درصد|Percentage  ratio:نسبت|Ratio  weight:وزن|Weight  size:اندازه|Size
company2:شرکت|Company  owner:مالک|Owner  creator:ایجادکننده|Creator  sender:فرستنده|Sender  receiver:گیرنده|Receiver
recipient:گیرنده|Recipient  holder:دارنده|Holder  agent:نماینده|Agent  operator:اپراتور|Operator  admin:مدیر سیستم|Admin
medical:پزشکی|Medical  health:سلامت|Health  clinic:درمانگاه|Clinic  visit:ویزیت|Visit  appointment:نوبت|Appointment
prescription:نسخه پزشکی|Prescription  diagnosis:تشخیص|Diagnosis  treatment:درمان|Treatment  therapy:درمان|Therapy
symptom:علامت|Symptom  disease:بیماری|Disease  drug:دارو|Drug  hospital:بیمارستان|Hospital  record:پرونده|Record
guardian:سرپرست|Guardian  school:مدرسه|School  grade:پایه|Grade  behavior:رفتار|Behavior  development:رشد|Development
consultation:مشاوره|Consultation  counselor:مشاور|Counselor  lead:سرنخ فروش|Lead  opportunity:فرصت فروش|Opportunity
campaign:کمپین|Campaign  case:پرونده|Case  incident:رخداد|Incident  contact:مخاطب|Contact  entity:موجودیت|Entity
attribute:ویژگی|Attribute  plugin:افزونه|Plugin  solution:راهکار|Solution  business:کسب‌وکار|Business
territory:قلمرو فروش|Territory  competitor:رقیب|Competitor  calendar:تقویم|Calendar  knowledge:دانش|Knowledge
article:مقاله|Article  template:الگو|Template  mailbox:صندوق پستی|Mailbox  goal:هدف|Goal  metric:شاخص|Metric
service:خدمت|Service  schedule:زمان‌بندی|Schedule  resource:منبع|Resource  equipment:تجهیزات|Equipment  site:سایت|Site
list:فهرست|List  marketing:بازاریابی|Marketing  connection:ارتباط|Connection  relationship:رابطه|Relationship
privilege:امتیاز دسترسی|Privilege  principal:مالک دسترسی|Principal  object:شیء|Object  mapping:نگاشت|Mapping
map:نگاشت|Mapping  label:برچسب|Label  form:فرم|Form  view:نما|View  chart:نمودار|Chart  dashboard:داشبورد|Dashboard
definition:تعریف|Definition  relation:رابطه|Relation  reward:پاداش|Reward
point:امتیاز|Point  growth:رشد|Growth  lifestyle:سبک زندگی|Lifestyle  vaccination:واکسیناسیون|Vaccination
invitation:دعوت|Invitation  height:قد|Height  allocation:تخصیص|Allocation  operation:عملیات|Operation
deployment:استقرار|Deployment  custom:سفارشی|Custom  enable:فعال|Enabled  managed:مدیریت‌شده|Managed
localized:ترجمه‌شده|Localized  string:رشته|String  feedback:بازخورد|Feedback  rating:رتبه|Rating  review:بازبینی|Review
vam:وام|Loan  tashilat:تسهیلات|Facility  mablagh:مبلغ|Amount  tarikh:تاریخ|Date  shomare:شماره|Number  nam:نام|Name
famil:نام خانوادگی|Last name  ostan:استان|Province  shahr:شهر|City  melli:ملی|National  hesab:حساب|Account
sanad:سند|Document  pardakht:پرداخت|Payment  daryaft:دریافت|Receipt  vaziat:وضعیت|Status  noe:نوع|Type
sharh:شرح|Description  karmand:کارمند|Employee  ghest:قسط|Installment  bimeh:بیمه|Insurance  refah:رفاه|Welfare
hoghoogh:حقوق|Salary  tedad:تعداد|Count  mojodi:موجودی|Balance  kala:کالا|Goods  anbar:انبار|Warehouse
faktor:فاکتور|Invoice  moshtari:مشتری|Customer  sherkat:شرکت|Company  vahed:واحد|Unit  semat:سمت|Position
takhfif:تخفیف|Discount  maliat:مالیات|Tax  pishnahad:پیشنهاد|Proposal  darkhast:درخواست|Request  shobe:شعبه|Branch
"""
VOCAB = {}  # a trailing digit in a key only disambiguates the source list (job2 -> job); first meaning wins
for _line in _V.strip().splitlines():
    for _item in re.split(r"\s{2,}", _line.strip()):
        _k, _v = _item.split(":", 1)
        _fa, _en = _v.split("|")
        VOCAB[re.sub(r"\d$", "", _k)] = VOCAB.get(re.sub(r"\d$", "", _k)) or (_fa, _en)
# Persian adjectives that come before the noun ("آخرین مانده"); every other word follows its head.
PRENOMINAL = {"last", "first", "max", "min"}
POST_QUALIFIERS = {"tmp", "temp", "staging", "stg", "old", "new", "copy", "bak", "archive", "active", "main"}
# Tokens that carry no business meaning in a name.
NOISE = {"tbl", "tb", "t", "dbo", "tab", "vw", "fk", "pk"}
AUDIT_VERBS = {"created", "create", "modified", "updated", "update", "deleted", "delete", "inserted", "changed"}
TIME_HEADS = {"at": ("زمان", "time"), "on": ("زمان", "time"), "date": ("تاریخ", "date"), "time": ("زمان", "time"),
              "datetime": ("زمان", "time"), "dt": ("تاریخ", "date")}
LEAD_PREFIXES = ("matched", "main", "parent", "source", "target", "destination", "from", "to", "related", "linked",
                 "primary", "secondary", "default", "current", "last", "original", "old", "new", "ref")

ATTRIBUTE_TIME = {"last", "expire", "expiry", "birth", "contract", "start", "end", "range", "from", "to", "next",
                  "until", "due", "deadline", "lease", "valid"}
# Table names ending in these are business events even without an event-date column (ORDER_REFUND).
EVENT_NOUNS = {"order", "transaction", "payment", "invoice", "request", "entry", "transfer", "deposit", "withdrawal",
               "charge", "topup", "purchase", "sale", "claim", "submission", "booking", "receipt", "voucher", "refund"}
ROLE_ORDER = ["staging", "reject_log", "audit_log", "outbox", "checkpoint", "reconciliation", "integration_log",
              "file_import", "junction", "lookup", "security", "settings", "detail", "transaction", "master", "other"]
FAMILY_SUFFIXES = {"tmp", "temp", "staging", "stg", "reject", "log", "checkpoint", "history", "hist", "archive",
                   "bak", "copy", "old", "error", "errors", "audit"}

SENSITIVE = [  # (kind, token sequences that mark a column)
    ("national_id", [("national", "code"), ("national", "id"), ("national", "no"), ("melli",), ("ssn",), ("passport",)]),
    ("personal", [("birth",), ("gender",), ("sex",), ("father",), ("mother",), ("marital",), ("full", "name"),
                  ("first", "name"), ("last", "name"), ("family", "name"), ("famil",), ("age",)]),
    ("contact", [("mobile",), ("phone",), ("tel",), ("email",), ("address",), ("postal",), ("zip",)]),
    ("financial", [("iban",), ("sheba",), ("card", "number"), ("card", "no"), ("account", "number"), ("cvv",),
                   ("cvv2",), ("salary",)]),
    ("secret", [("password",), ("pwd",), ("secret",), ("api", "key"), ("access", "token"), ("auth", "token"),
                ("refresh", "token"), ("api", "token"), ("pin",)]),
]


def split_name(name):
    """ORDER_PAYMENT_TMP / OrderPaymentTmp / orderPayment2 -> ['order', 'payment', 'tmp']."""
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    parts = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", parts)
    parts = re.sub(r"([A-Za-z])(\d)", r"\1 \2", parts)  # ADDRESS1 -> ADDRESS 1
    return [p.lower() for p in re.split(r"[^A-Za-z0-9]+|\s+", parts) if p and not p.isdigit()]


INFLECTIONS = (("ies", "y"), ("ses", "s"), ("es", ""), ("s", ""), ("ed", ""), ("d", ""))


def norm(tok):
    """Vocabulary form of a token: simple English singular / past participle, then a misspelling with one
    clear nearest word (RECONCILIATON -> reconciliation). An ambiguous misspelling stays as it is."""
    for suffix, repl in INFLECTIONS:
        if tok.endswith(suffix) and len(tok) > len(suffix) + 2 and tok[: -len(suffix)] + repl in VOCAB:
            return tok[: -len(suffix)] + repl
    if tok in VOCAB:
        return tok
    best = spelling(tok)
    return best[0] if len(best) == 1 else tok


_SPELL = {}


def _inflected(tok):
    """True when tok is a vocabulary word with or without a simple ending (ENABLE / ENABLED, ORDERS)."""
    return (tok in VOCAB or any(tok.endswith(s) and tok[:-len(s)] + r in VOCAB for s, r in INFLECTIONS)
            or any(tok + s in VOCAB for s in ("d", "ed", "s", "es")))


def _plausible_typo(tok, k):
    """A misspelling keeps the first letter, the length within 2, and is not one word inside the other
    (BORDER/ORDER, OPERATION/COOPERATION are different words); a cut-off prefix (LOCATIO) counts."""
    if tok[0] != k[0] or abs(len(tok) - len(k)) > 2 or k in tok:
        return False
    return tok not in k or (k.startswith(tok) and len(tok) >= 8)


def spelling(tok):
    """Vocabulary words a likely-misspelled token stands for: [] = not a typo, 2+ = ambiguous."""
    if tok not in _SPELL:
        out = []
        if len(tok) >= 6 and not _inflected(tok) and not segment(tok):
            # same letters in another order (CONTRCAT -> CONTRACT) is the likeliest typo: small bonus
            scored = sorted(((difflib.SequenceMatcher(None, tok, k).ratio() + (0.1 if sorted(tok) == sorted(k) else 0), k)
                             for k in VOCAB if len(k) >= 5 and _plausible_typo(tok, k)), reverse=True)
            if scored and scored[0][0] >= 0.86:
                out = sorted(k for r, k in scored if r >= scored[0][0] - 0.02)
        _SPELL[tok] = out
    return _SPELL[tok]


AFFIXES = {"id", "on", "of", "is", "has", "by", "db", "ai", "in", "un", "re", "sub", "no", "to", "at", "as", "for"}
_SEG = {}


def segment(tok):
    """Split a run-together name (CREATEDON, ISDELETED, CATEGORYID, AICONFIGURATION) into known words;
    [] when it is not a clean compound of vocabulary words and short affixes."""
    if tok in _SEG:
        return _SEG[tok]
    best = []
    if len(tok) >= 6 and not _inflected(tok):
        known = lambda w: _inflected(w) and len(w) >= 3  # noqa: E731
        ways = {0: []}
        for i in range(1, len(tok) + 1):
            for j in range(max(0, i - 16), i):
                piece = tok[j:i]
                if j in ways and (known(piece) or piece in AFFIXES):
                    cand = ways[j] + [piece]
                    if i not in ways or len(cand) < len(ways[i]):
                        ways[i] = cand
        parts = ways.get(len(tok), [])
        if len(parts) >= 2 and any(known(x) and len(x) >= 4 for x in parts):
            best = parts
    _SEG[tok] = best
    return best


def words(name):
    out = []
    for tok in split_name(name):
        if tok in NOISE:
            continue
        pieces = segment(tok) if not _inflected(tok) else []
        out.extend(norm(x) for x in (pieces or [tok]) if x not in NOISE)
    return out


def phrase(toks, lang):
    """Business phrase for name tokens. Persian reverses noun compounds (Order Payment -> پرداخت سفارش)."""
    toks = [t for t in toks if t]
    if not toks:
        return ""
    if lang == "en":
        return " ".join(VOCAB[t][1] if t in VOCAB else t.upper() for t in toks)
    tail = []  # ORDER_PAYMENT_TMP -> «پرداخت سفارش موقت»: a trailing qualifier ends the Persian phrase too
    while len(toks) > 1 and toks[-1] in POST_QUALIFIERS:
        tail.insert(0, _fa(toks.pop()))
    units, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t in PRENOMINAL and i + 1 < len(toks):
            units.append(f"{VOCAB[t][0]} {_fa(toks[i + 1])}")
            i += 2
        else:
            units.append(_fa(t))
            i += 1
    return " ".join(list(reversed(units)) + tail)


def _fa(t):
    return VOCAB[t][0] if t in VOCAB else t.upper()


def name_phrase(name, lang):
    toks = words(name)
    if len(toks) > 1 and toks[-1] == "id":
        toks = toks[:-1]
    return phrase(toks, lang) or name


def _has_seq(toks, seq):
    n = len(seq)
    return any(tuple(toks[i:i + n]) == seq for i in range(len(toks) - n + 1))


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def column_kind(col, toks, is_pk, fk_target, allowed):
    """(category, meaning params) for one column, from its name tokens, type and keys."""
    t = col["data_type"].lower()
    last = toks[-1] if toks else ""
    numeric = t in ("number", "decimal", "numeric", "money", "smallmoney", "float", "real", "int", "bigint",
                    "smallint", "tinyint", "binary_double", "binary_float")
    if is_pk and len(toks) <= 2 and last == "id":
        return "pk", {}
    if fk_target:
        return "fk", {"target": fk_target}
    if last in ("by",) and any(v in toks for v in AUDIT_VERBS):
        return "audit_user", {"what": _audit_word(toks)}
    if last in TIME_HEADS and any(v in toks for v in AUDIT_VERBS):
        return "audit_time", {"what": _audit_word(toks)}
    if toks[:1] == ["is"] and any(v in toks for v in ("deleted",)) or toks == ["deleted"]:
        return "soft_delete", {}
    for kind, seqs in SENSITIVE:
        if any(_has_seq(toks, s) for s in seqs):
            return f"sensitive_{kind}", {}
    if toks[:1] in (["is"], ["has"], ["can"]) or t == "bit" or (allowed and sorted(allowed) == ["0", "1"]):
        return "flag", {"subject": toks[1:] if toks[:1] in (["is"], ["has"], ["can"]) else toks}
    if last in ("status", "state"):
        return "status", {"values": allowed}
    if last in ("type", "kind", "category", "level", "group"):
        return "classifier", {"values": allowed}
    if numeric and any(x in toks for x in ("amount", "amt", "price", "cost", "fee", "balance", "debit", "credit",
                                            "salary", "wage", "debt", "mablagh", "tax", "discount")):
        return "money", {}
    if numeric and any(x in toks for x in ("count", "cnt", "qty", "quantity", "attempt", "total", "tedad")):
        return "count", {}
    if any(x in toks for x in ("rate", "percent", "percentage", "ratio")):
        return "rate", {}
    if (last in TIME_HEADS or "date" in toks or "datetime" in toks or t.startswith(("date", "time", "smalldate"))
            or "timestamp" in t):
        return "time", {}
    if any(x in toks for x in ("json", "xml", "payload")):
        return "payload", {}
    if any(x in toks for x in ("rrn", "tracking", "idempotency", "reference", "ref", "uuid", "guid", "stan")) \
            or ("message" in toks and last == "number"):
        return "external_ref", {}
    if any(x in toks for x in ("file", "path", "attachment", "image", "photo", "extension")) \
            or t in ("blob", "varbinary", "image", "bfile"):
        return "file", {}
    if any(x in toks for x in ("error", "exception")) or last in ("attempt", "retry"):
        return "error_info", {}
    if last in ("number", "no", "num", "code", "serial", "id"):
        return "identifier", {}
    if last in ("name", "title", "description", "desc", "note", "comment", "text", "sharh"):
        return "text", {}
    if any(x in toks for x in ("lat", "latitude", "lng", "lon", "longitude", "city", "province", "country", "location",
                               "region")):
        return "geo", {}
    return "other", {}


def _audit_word(toks):
    for v in toks:
        if v in AUDIT_VERBS:
            return "create" if v.startswith("creat") else ("delete" if v.startswith("delet") else "modify")
    return "modify"


# ---------------------------------------------------------------------------
# Relations (explicit FK + implicit, inferred from *_ID names)
# ---------------------------------------------------------------------------

def _table_index(tables):
    return {name: words(name) for name in tables}


def resolve_reference(table, col_name, index, own_toks):
    """Table that a *_ID column most likely points to (no FK declared), or None."""
    toks = words(col_name)
    if len(toks) < 2 or toks[-1] != "id":
        return None
    base = toks[:-1]
    for start in range(len(base)):
        cand = base[start:]
        hits = [t for t, tt in index.items() if tt == cand and t != table]
        if len(hits) == 1:
            return hits[0]
        ending = [t for t, tt in index.items() if tt[-len(cand):] == cand and t != table and len(tt) > len(cand)]
        if ending and start == len(base) - 1:
            # PAYMENT_ID inside ORDER_PAYMENT_REJECT_LOG -> ORDER_PAYMENT (shares the table's prefix)
            pref = [t for t in ending if own_toks[:len(index[t])] == index[t]]
            if len(pref) == 1:
                return pref[0]
    joined = "_".join(base)
    names = {"_".join(tt): t for t, tt in index.items() if t != table}
    close = difflib.get_close_matches(joined, list(names), n=1, cutoff=0.88)
    return names[close[0]] if close else None


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def analyze_business(snap):
    tables = snap["tables"]
    rels = [r for r in snap["relationships"] if r["target_table"] and not r["external"]]
    findings = analyze(snap)
    allowed = {(f["table"], f["column"]): f["params"]["values"] for f in findings if f["code"] == "chk_allowed_values"}
    copy_of = {f["table"]: f["params"]["other"] for f in findings if f["code"] == "inf_copy_of"}
    index = _table_index(tables)

    fk_cols = {(r["source_table"], c): r["target_table"] for r in rels for c in r["source_columns"]}
    implicit = []
    for name in sorted(tables):
        for c in tables[name]["columns"]:
            if (name, c["name"]) in fk_cols or any(c["name"] in r["source_columns"] for r in snap["relationships"]
                                                   if r["source_table"] == name):
                continue
            target = resolve_reference(name, c["name"], index, index[name])
            if target:
                implicit.append({"table": name, "column": c["name"], "target": target})
    imp_cols = {(i["table"], i["column"]): i["target"] for i in implicit}

    out_links, in_links = defaultdict(list), defaultdict(list)
    for r in rels:
        out_links[r["source_table"]].append((r["target_table"], r["source_columns"], "fk"))
        in_links[r["target_table"]].append((r["source_table"], r["source_columns"], "fk"))
    for i in implicit:
        out_links[i["table"]].append((i["target"], [i["column"]], "implicit"))
        in_links[i["target"]].append((i["table"], [i["column"]], "implicit"))

    result_tables, sensitive = {}, []
    for name in sorted(tables):
        t = tables[name]
        toks = index[name]
        pk = next((c["columns"] for c in t["constraints"] if c["type"] == "P"), [])
        cols = []
        for c in t["columns"]:
            ctoks = words(c["name"])
            target = fk_cols.get((name, c["name"])) or imp_cols.get((name, c["name"]))
            vals = allowed.get((name, c["name"]))
            kind, params = column_kind(c, ctoks, c["name"] in pk, target, vals)
            cols.append({"column": c["name"], "kind": kind, "params": params, "tokens": ctoks,
                         "implicit": (name, c["name"]) in imp_cols, "nullable": c["nullable"]})
            if kind.startswith("sensitive_"):
                sensitive.append({"table": name, "column": c["name"], "kind": kind[len("sensitive_"):]})
        role, role_params = classify(name, t, toks, cols, out_links[name], in_links[name], index, copy_of)
        result_tables[name] = {
            "tokens": toks, "role": role, "role_params": role_params, "columns": cols,
            "out": sorted({(x[0], x[2]) for x in out_links[name]}), "in": sorted({(x[0], x[2]) for x in in_links[name]}),
            "copy_of": copy_of.get(name), "comment": t["comment"],
        }

    modules = build_modules(result_tables, index)
    for m in modules:
        for tname in m["tables"]:
            result_tables[tname]["module"] = m["key"]
    processes = find_processes(result_tables, index, rels, implicit)
    quality = naming_quality(tables, index, implicit, rels)
    glossary = build_glossary(tables)
    questions = build_questions(result_tables, glossary)
    for tname, bt in result_tables.items():
        bt["statements"] = table_statements(tname, bt, result_tables)
        bt["relations"] = relation_statements(tname, tables, rels, implicit)
    return {
        "tables": result_tables, "modules": modules, "processes": processes, "implicit_relations": implicit,
        "sensitive": sensitive, "quality": quality, "glossary": glossary, "questions": questions,
        "summary": {"tables": len(tables), "modules": len(modules), "processes": len(processes),
                    "roles": dict(sorted(Counter(b["role"] for b in result_tables.values()).items())),
                    "implicit": len(implicit), "sensitive": len(sensitive)},
    }


def classify(name, t, toks, cols, out_links, in_links, index, copy_of):
    """Business role of a table, first matching rule in ROLE_ORDER."""
    kinds = Counter(c["kind"] for c in cols)
    ctoks = {tok for c in cols for tok in c["tokens"]}
    last = toks[-1] if toks else ""
    family = [x for x in toks if x not in FAMILY_SUFFIXES]
    base = next((n for n, tt in index.items() if tt == family and n != name), None) if family != toks else None
    targets = sorted({x[0] for x in out_links})
    non_meta = [c for c in cols if c["kind"] not in ("pk", "fk", "audit_user", "audit_time", "soft_delete")]

    if last in ("tmp", "temp", "staging", "stg") or toks[:1] in (["tmp"], ["temp"], ["stg"]):
        return "staging", {"base": base or copy_of.get(name)}
    if "reject" in toks or ("error" in toks and "log" in toks) or ("failed" in toks):
        return "reject_log", {"base": base}
    if last in ("log", "history", "hist", "audit", "trail", "journal", "archive") \
            or {"oldvalue", "newvalue"} <= ctoks or ({"old", "new", "value"} <= ctoks and "action" in ctoks):
        return "audit_log", {"base": base}
    if {"outbox", "inbox", "queue"} & set(toks) or ({"attempt", "next"} <= ctoks and "lease" in ctoks):
        return "outbox", {"cols": [c["column"] for c in cols if c["kind"] in ("count", "error_info")][:4]}
    if "checkpoint" in toks or "batch" in toks or ("range" in ctoks and "fetched" in ctoks):
        return "checkpoint", {"base": _family_base(toks, index, name), "targets": targets}
    if any(x.startswith("reconcil") for x in toks):
        return "reconciliation", {"targets": targets}
    if ("json" in ctoks and ("request" in ctoks or "response" in ctoks)) or {"request", "response"} <= ctoks:
        return "integration_log", {"cols": [c["column"] for c in cols if c["kind"] in ("payload", "external_ref")][:5]}
    if "import" in ctoks and "file" in ctoks:
        return "file_import", {}
    fk_count = len({x[0] for x in out_links})
    if fk_count >= 2 and len(non_meta) <= 1 and kinds["money"] == 0:
        return "junction", {"targets": targets}
    if (last in ("type", "kind", "category", "level", "levels", "group", "status", "lookup")
            or "lookup" in toks) and len(non_meta) <= 4 and not fk_count:
        return "lookup", {"users": sorted({x[0] for x in in_links})}
    if not fk_count and in_links and len(non_meta) <= 2 and any(c["kind"] == "text" for c in cols):
        return "lookup", {"users": sorted({x[0] for x in in_links})}
    if {"user", "role", "permission", "login", "access"} & set(toks) or "password" in ctoks:
        return "security", {}
    if {"setting", "settings", "config", "configuration", "parameter", "param"} & set(toks):
        return "settings", {}
    for tgt in targets:
        tt = index.get(tgt, [])
        if tt and toks[:len(tt)] == tt and len(toks) > len(tt) and tgt != name:
            return "detail", {"parent": tgt}
    # an event time says when the row's business event happened (not LAST_*, contract/birth/expiry dates)
    has_event_time = any(c["kind"] == "time" and not ATTRIBUTE_TIME & set(c["tokens"]) for c in cols)
    money = [c["column"] for c in cols if c["kind"] == "money"][:4]
    if (has_event_time or last in EVENT_NOUNS) and (kinds["money"] or (fk_count and kinds["status"])):
        return "transaction", {"money": money}
    naming = ("text", "identifier", "sensitive_personal", "sensitive_national_id")  # a name, title, code or identity
    if len({x[0] for x in in_links}) >= 2 or (in_links and any(c["kind"] in naming for c in cols)):
        return "master", {"n": len({x[0] for x in in_links})}
    if has_event_time and fk_count:
        return "transaction", {"money": []}
    return "other", {}


def _family_base(toks, index, name):
    family = [x for x in toks if x not in FAMILY_SUFFIXES]
    return next((n for n, tt in index.items() if tt == family and n != name), None)


def build_modules(bt, index):
    """Group tables into business modules: shared leading name token first, then by relationships."""
    # A leading token shared by many tables that is not a business word is a vendor/namespace prefix
    # (msdyn_, adx_): group those tables by their next word instead.
    lead = Counter(b["tokens"][0] for b in bt.values() if len(b["tokens"]) > 1)
    namespaces = {tok for tok, n in lead.items() if n >= max(5, len(bt) // 20) and tok not in VOCAB}
    first = {n: (b["tokens"][1] if b["tokens"][:1] and b["tokens"][0] in namespaces and len(b["tokens"]) > 1
                 else (b["tokens"][0] if b["tokens"] else n.lower())) for n, b in bt.items()}
    counts = Counter(first.values())
    groups = defaultdict(list)
    loose = []
    for n in sorted(bt):
        (groups[first[n]] if counts[first[n]] >= 2 else loose).append(n)
    for n in list(loose):  # a lookup used by exactly one other loose table forms a module with it
        users = {x[0] for x in bt[n]["in"]}
        if n in loose and bt[n]["role"] == "lookup" and len(users) == 1 and next(iter(users)) in loose:
            p = next(iter(users))
            for x in (p, n):
                if x in loose:
                    groups[first[p]].append(x)
                    loose.remove(x)
    owner = {n: k for k, ns in groups.items() for n in ns}
    shared = []
    for _ in range(2):  # a second pass lets chains of single tables follow each other
        for n in list(loose):
            linked = Counter(owner[x[0]] for x in bt[n]["out"] + bt[n]["in"] if x[0] in owner)
            users = {owner[x[0]] for x in bt[n]["in"] if x[0] in owner}
            if len(users) >= 2 and bt[n]["role"] not in ("lookup",) and len(bt[n]["in"]) >= 3:
                continue  # used across modules: shared
            if linked:
                key = sorted(linked.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                groups[key].append(n)
                owner[n] = key
                loose.remove(n)
    for n in loose:
        users = {owner[x[0]] for x in bt[n]["in"] if x[0] in owner}
        if len(users) >= 2:
            shared.append(n)
        else:
            groups[f"~{first[n]}"].append(n)
            owner[n] = f"~{first[n]}"
    modules = []
    for key, ns in groups.items():
        ns = sorted(ns)
        main = max(ns, key=lambda n: (len(bt[n]["in"]), bt[n]["role"] == "master", -len(n), n))
        tok = key.lstrip("~")
        modules.append({"key": key, "token": tok, "tables": ns, "main": main, "shared": False,
                        "roles": dict(sorted(Counter(bt[n]["role"] for n in ns).items()))})
    if shared:
        modules.append({"key": "*shared", "token": "", "tables": sorted(shared), "main": None, "shared": True,
                        "roles": dict(sorted(Counter(bt[n]["role"] for n in shared).items()))})
    modules.sort(key=lambda m: (m["shared"], -len(m["tables"]), m["key"]))
    links = Counter()
    for m in modules:
        for n in m["tables"]:
            for tgt, _ in bt[n]["out"]:
                other = next((x["key"] for x in modules if tgt in x["tables"]), None)
                if other and other != m["key"]:
                    links[(m["key"], other)] += 1
    for m in modules:
        m["links"] = sorted(((k[1], v) for k, v in links.items() if k[0] == m["key"]), key=lambda kv: (-kv[1], kv[0]))
    return modules


def find_processes(bt, index, rels, implicit):
    """Business processes recognised from table families and column patterns."""
    out = []
    by_role = defaultdict(list)
    for n, b in bt.items():
        by_role[b["role"]].append(n)
    families = defaultdict(list)
    for n, b in bt.items():
        fam = tuple(x for x in b["tokens"] if x not in FAMILY_SUFFIXES)
        families[fam].append(n)
    for fam, members in sorted(families.items()):
        roles = {bt[m]["role"]: m for m in members}
        if len(members) >= 2 and ({"staging", "reject_log", "checkpoint"} & set(roles)):
            core = next((m for m in members if bt[m]["tokens"] == list(fam)), None)
            out.append({"code": "proc_ingest", "params": {
                "core": core, "staging": roles.get("staging"), "reject": roles.get("reject_log"),
                "checkpoint": roles.get("checkpoint")}, "tables": sorted(members), "basis": ["name"]})
    for n in sorted(by_role["reconciliation"]):
        out.append({"code": "proc_reconcile", "params": {"table": n, "targets": bt[n]["role_params"]["targets"]},
                    "tables": [n] + bt[n]["role_params"]["targets"], "basis": ["name", "relationship"]})
    matched = sorted({n for n, b in bt.items() for c in b["columns"] if "matched" in c["tokens"]
                      and b["role"] != "reconciliation"})
    if matched:
        out.append({"code": "proc_matching", "params": {"tables": matched}, "tables": matched, "basis": ["name"]})
    for n in sorted(by_role["outbox"]):
        out.append({"code": "proc_outbox", "params": {"table": n, "sources": [x[0] for x in bt[n]["out"]]},
                    "tables": [n], "basis": ["name"]})
    for n in sorted(by_role["integration_log"]):
        users = sorted({x[0] for x in bt[n]["in"]})
        out.append({"code": "proc_integration", "params": {"table": n, "users": users}, "tables": [n] + users,
                    "basis": ["name", "relationship"]})
    for n in sorted(by_role["file_import"]):
        users = sorted({x[0] for x in bt[n]["in"]})
        out.append({"code": "proc_file_import", "params": {"table": n, "users": users}, "tables": [n] + users,
                    "basis": ["name"]})
    sec = sorted(by_role["security"])
    if sec:
        out.append({"code": "proc_access", "params": {"tables": sec}, "tables": sec, "basis": ["name"]})
    audit = sorted(n for n in by_role["audit_log"])
    if audit:
        out.append({"code": "proc_audit", "params": {"tables": audit}, "tables": audit, "basis": ["name"]})
    for n, b in sorted(bt.items()):
        for c in b["columns"]:
            if c["kind"] == "status" and b["role"] in ("transaction", "master", "detail", "other", "outbox",
                                                       "checkpoint", "reconciliation", "file_import"):
                out.append({"code": "proc_lifecycle", "params": {"table": n, "column": c["column"],
                                                                 "values": c["params"].get("values")},
                            "tables": [n], "basis": ["name"] + (["check"] if c["params"].get("values") else [])})
    for n, b in sorted(bt.items()):
        if b["role"] == "detail":
            out.append({"code": "proc_master_detail", "params": {"parent": b["role_params"]["parent"], "child": n},
                        "tables": [b["role_params"]["parent"], n], "basis": ["name", "relationship"]})
    return out


def naming_quality(tables, index, implicit, rels):
    """Likely misspellings, one concept spelled two ways, and implicit relationships."""
    all_toks = Counter(tok for n in tables for tok in split_name(n))
    for t in tables.values():
        for c in t["columns"]:
            all_toks.update(split_name(c["name"]))
    out = []
    for tok in sorted(all_toks):
        close = spelling(tok)
        if close:
            where = sorted({n for n in tables if tok in split_name(n)}
                           | {f"{n}.{c['name']}" for n, t in tables.items() for c in t["columns"]
                              if tok in split_name(c["name"])})[:6]
            out.append({"code": "q_typo", "params": {"token": tok.upper(), "suggest": [c.upper() for c in close],
                                                     "where": where}})
    for i in implicit:
        out.append({"code": "q_implicit_fk", "params": i})
    for r in rels:  # FK column spelled differently from the table it references (CORPORATON_TYPE_ID -> CORPERATION_TYPE)
        if len(r["source_columns"]) != 1:
            continue
        col = split_name(r["source_columns"][0])
        if len(col) < 2 or col[-1] != "id":
            continue
        base, target = "_".join(col[:-1]), "_".join(split_name(r["target_table"]))
        same_words = words(r["source_columns"][0])[:-1] == words(r["target_table"])  # ROLE_LEVEL_ID -> ROLE_LEVELS
        if not same_words and not base.endswith(target) and difflib.SequenceMatcher(None, base, target).ratio() >= 0.85:
            out.append({"code": "q_spelling_mismatch", "params": {
                "table": r["source_table"], "column": r["source_columns"][0], "target": r["target_table"]}})
    return out


def build_glossary(tables):
    counter = Counter()
    for n, t in tables.items():
        counter.update(words(n))
        for c in t["columns"]:
            counter.update(words(c["name"]))
    return [{"term": tok, "count": n, "known": tok in VOCAB} for tok, n in
            sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])) if tok not in ("id", "by", "at", "is", "has")]


def build_questions(bt, glossary):
    out = []
    unknown = [g["term"] for g in glossary if not g["known"] and g["count"] >= 2 and len(g["term"]) <= 12][:15]
    if unknown:
        out.append({"code": "q_unknown_terms", "params": {"terms": [u.upper() for u in unknown]}})
    for n, b in sorted(bt.items()):
        if b["role"] == "other":
            out.append({"code": "q_unclear_table", "params": {"table": n}})
        for c in b["columns"]:
            if c["kind"] in ("status", "classifier") and not c["params"].get("values") and b["role"] != "lookup":
                out.append({"code": "q_status_values", "params": {"table": n, "column": c["column"]}})
    return out


def table_statements(name, b, bt):
    """Business sentences for one table (template code, params, basis)."""
    s = []
    if b["comment"]:
        s.append({"code": "st_comment", "params": {"text": b["comment"]}, "basis": ["comment"]})
    s.append({"code": f"role_{b['role']}", "params": dict(b["role_params"], name=name), "basis": ["name", "relationship"]})
    if b["copy_of"] and b["role"] != "staging":
        s.append({"code": "st_copy_of", "params": {"other": b["copy_of"]}, "basis": ["structure"]})
    kinds = defaultdict(list)
    for c in b["columns"]:
        kinds[c["kind"]].append(c["column"])
    if kinds["money"] and b["role"] not in ("transaction",):
        s.append({"code": "st_money", "params": {"cols": kinds["money"]}, "basis": ["name", "type"]})
    starts = [c for c in kinds["time"] if any(x in c.upper() for x in ("START", "FROM", "BEGIN"))]
    ends = [c for c in kinds["time"] if any(x in c.upper() for x in ("END", "TO_", "EXPIRE", "UNTIL"))]
    if starts and ends:
        s.append({"code": "st_period", "params": {"cols": starts + ends}, "basis": ["name"]})
    if kinds["status"]:
        s.append({"code": "st_status", "params": {"cols": kinds["status"]}, "basis": ["name"]})
    if kinds["external_ref"]:
        s.append({"code": "st_external_ref", "params": {"cols": kinds["external_ref"]}, "basis": ["name"]})
    if kinds["file"]:
        s.append({"code": "st_file", "params": {"cols": kinds["file"]}, "basis": ["name", "type"]})
    if kinds["audit_time"] or kinds["audit_user"]:
        s.append({"code": "st_audit", "params": {"cols": kinds["audit_time"] + kinds["audit_user"]}, "basis": ["name"]})
    if kinds["soft_delete"]:
        s.append({"code": "st_soft_delete", "params": {"cols": kinds["soft_delete"]}, "basis": ["name"]})
    sens = [c for k, v in kinds.items() if k.startswith("sensitive_") for c in v]
    if sens:
        s.append({"code": "st_sensitive", "params": {"cols": sens}, "basis": ["name"]})
    return s


def relation_statements(name, tables, rels, implicit):
    out = []
    for r in rels:
        if r["source_table"] != name:
            continue
        cols = {c["name"]: c for c in tables[name]["columns"]}
        optional = any(cols.get(c, {}).get("nullable") for c in r["source_columns"])
        unique = any(c["type"] in ("P", "U") and sorted(c["columns"]) == sorted(r["source_columns"])
                     for c in tables[name]["constraints"])
        out.append({"code": "rel_one_to_one" if unique else "rel_many_to_one",
                    "params": {"src": name, "tgt": r["target_table"], "cols": r["source_columns"], "optional": optional},
                    "basis": ["relationship"]})
    for i in implicit:
        if i["table"] == name:
            out.append({"code": "rel_implicit", "params": {"src": name, "tgt": i["target"], "cols": [i["column"]]},
                        "basis": ["name"]})
    return out
