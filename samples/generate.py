"""Deterministic synthetic-data generator for SDSA samples.

Writes the larger sample files alongside this script. Uses stdlib only.
Re-running produces byte-identical output (fixed seed).

    python3 samples/generate.py
"""
from __future__ import annotations

import csv
import datetime as dt
import pathlib
import random
import unicodedata

SEED = 42
HERE = pathlib.Path(__file__).resolve().parent

# --- name pools ------------------------------------------------------------

FIRST_NAMES_EN = [
    "Alice", "Bob", "Carol", "David", "Eve", "Frank", "Grace", "Henry",
    "Irene", "Jack", "Karen", "Liam", "Maria", "Noah", "Olivia", "Paul",
    "Quinn", "Rachel", "Samuel", "Tina", "Uma", "Victor", "Wendy", "Xavier",
    "Yara", "Zane", "Aaron", "Beth", "Chris", "Dana", "Evan", "Fiona",
    "Greg", "Hannah", "Ian", "Julia", "Kyle", "Lisa", "Marcus", "Nora",
    "Oscar", "Priya", "Ravi", "Sophia", "Tomas", "Una", "Vlad", "Will",
    "Xena", "Yusuf",
]
LAST_NAMES_EN = [
    "Johnson", "Smith", "Davis", "Lee", "Martinez", "Turner", "Park",
    "Wilson", "Chen", "Brown", "Nguyen", "Murphy", "Silva", "Kim", "Tran",
    "Anderson", "Roberts", "Gomez", "Patel", "Yoshida", "Khan", "Rossi",
    "Fischer", "Dubois", "Novak", "Hansen", "Suzuki", "Kowalski", "O'Brien",
    "Carter", "Moore", "Wright", "Green", "Adams", "Hill", "Baker", "Clark",
    "Young", "Walker", "Hall",
]

FIRST_NAMES_TW = [
    "怡君", "建國", "美玲", "志明", "雅婷", "俊傑", "佩珊", "宗翰",
    "雅筑", "文浩", "婉婷", "博文", "惠如", "維倫", "靜宜", "家豪",
    "淑芬", "冠廷", "欣怡", "柏翰",
]
LAST_NAMES_TW = ["林", "王", "陳", "張", "李", "黃", "吳", "蔡", "許", "楊",
                 "鄭", "謝", "洪", "葉", "蘇", "周", "曾", "劉", "郭", "何"]

DEPARTMENTS = [
    ("Engineering",     0.25, (85_000, 25_000)),
    ("Sales",           0.15, (75_000, 20_000)),
    ("Marketing",       0.10, (80_000, 18_000)),
    ("Customer Support",0.12, (55_000, 12_000)),
    ("Operations",      0.10, (70_000, 15_000)),
    ("HR",              0.06, (72_000, 14_000)),
    ("Finance",         0.08, (95_000, 22_000)),
    ("Legal",           0.04, (120_000, 25_000)),
    ("Data Science",    0.06, (110_000, 28_000)),
    ("Product",         0.04, (105_000, 22_000)),
]
TITLES = {
    "Engineering": ["SWE I", "SWE II", "Senior SWE", "Staff SWE", "Principal SWE", "EM"],
    "Sales": ["AE", "Senior AE", "Sales Manager", "SDR", "Account Director"],
    "Marketing": ["Marketing Specialist", "Sr Marketing Mgr", "Growth Lead"],
    "Customer Support": ["CS Rep", "CS Lead", "CS Manager"],
    "Operations": ["Ops Analyst", "Ops Manager", "Ops Director"],
    "HR": ["HR Partner", "Recruiter", "HR Director"],
    "Finance": ["Analyst", "Sr Analyst", "Controller", "Finance Director"],
    "Legal": ["Legal Counsel", "Sr Counsel", "GC"],
    "Data Science": ["DS I", "DS II", "Senior DS", "ML Engineer"],
    "Product": ["PM", "Sr PM", "Director of Product"],
}

SF_ZIPS = ["94103", "94107", "94110", "94114", "94117", "94121"]
NYC_ZIPS = ["10001", "10002", "10003", "10013", "10014", "10016"]
TW_CITIES = [
    ("台北市信義區", "信義路五段7號", "110"),
    ("台北市大安區", "忠孝東路四段201號", "106"),
    ("新北市板橋區", "縣民大道二段7號", "220"),
    ("台中市西屯區", "台灣大道三段99號", "407"),
    ("台中市北屯區", "文心路四段955號", "406"),
    ("高雄市鼓山區", "明誠三路56號", "804"),
    ("高雄市左營區", "博愛二路777號", "813"),
    ("桃園市桃園區", "中正路1095號", "330"),
    ("新竹市東區", "光復路二段101號", "300"),
    ("台南市東區", "東門路一段99號", "701"),
]

MERCHANT_CATEGORIES = [
    ("groceries",     0.25, (15, 180)),
    ("restaurants",   0.20, (20, 200)),
    ("fuel",          0.10, (30, 90)),
    ("subscriptions", 0.08, (5, 60)),
    ("electronics",   0.07, (50, 2000)),
    ("travel",        0.08, (100, 3000)),
    ("healthcare",    0.10, (25, 500)),
    ("retail",        0.12, (20, 400)),
]
COUNTRIES = [("US", 0.70), ("CA", 0.10), ("GB", 0.08), ("TW", 0.07), ("JP", 0.05)]

# Luhn-valid test card numbers (reserved by card networks for testing).
TEST_CARDS = [
    "4111111111111111",  # Visa
    "4012888888881881",  # Visa
    "5500000000000004",  # MasterCard
    "5555555555554444",  # MasterCard
    "340000000000009",   # Amex
    "378282246310005",   # Amex
    "6011111111111117",  # Discover
    "3530111333300000",  # JCB
]

PATHS = ["/api/orders", "/api/profile", "/api/billing", "/api/search",
         "/api/cart", "/api/checkout", "/api/reports", "/api/settings"]
UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/127.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) Firefox/128.0",
    "curl/8.4.0",
    "okhttp/4.12.0",
]

# --- helpers ---------------------------------------------------------------

def ascii_slug(s: str) -> str:
    """Best-effort ASCII slug for email locals."""
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c.lower() for c in stripped if c.isalnum()) or "user"


def weighted_choice(rng: random.Random, items):
    weights = [w for _, w, *_ in items]
    return rng.choices(items, weights=weights, k=1)[0]


def normal_clamped(rng: random.Random, mean: float, sd: float,
                   lo: float, hi: float) -> float:
    v = rng.gauss(mean, sd)
    return max(lo, min(hi, v))


def random_date(rng: random.Random, start: dt.date, end: dt.date) -> dt.date:
    days = (end - start).days
    return start + dt.timedelta(days=rng.randint(0, days))


def phone_us(rng: random.Random) -> str:
    area = rng.choice([415, 212, 310, 617, 312, 206])
    return f"+1{area}{rng.randint(5_550_000, 5_559_999):07d}"[:12]


def phone_tw(rng: random.Random) -> str:
    # TW mobile: +8869XXXXXXXX (9 digits after 9)
    return f"+8869{rng.randint(10_000_000, 99_999_999):08d}"


# --- employees_large.csv ---------------------------------------------------

def gen_employees(n: int = 1000) -> None:
    rng = random.Random(SEED)
    path = HERE / "employees_large.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["employee_id", "full_name", "email", "phone", "dob",
                    "zip", "department", "job_title", "salary", "hire_date"])
        zips = SF_ZIPS + NYC_ZIPS
        dob_start = dt.date(1970, 1, 1)
        dob_end = dt.date(2002, 12, 31)
        hire_start = dt.date(2010, 1, 1)
        hire_end = dt.date(2025, 12, 31)
        for i in range(1, n + 1):
            first = rng.choice(FIRST_NAMES_EN)
            last = rng.choice(LAST_NAMES_EN)
            full = f"{first} {last}"
            email = f"{ascii_slug(first)}.{ascii_slug(last)}{i}@acme.example"
            phone = phone_us(rng)
            dob = random_date(rng, dob_start, dob_end).isoformat()
            z = rng.choice(zips)
            dept, _wt, (sal_mean, sal_sd) = weighted_choice(rng, DEPARTMENTS)
            title = rng.choice(TITLES[dept])
            salary = round(normal_clamped(rng, sal_mean, sal_sd, 40_000, 250_000))
            hire = random_date(rng, hire_start, hire_end).isoformat()
            w.writerow([f"E{i:06d}", full, email, phone, dob, z, dept,
                        title, salary, hire])


# --- transactions_large.csv ------------------------------------------------

def gen_transactions(n: int = 5000, pool_size: int = 300) -> None:
    rng = random.Random(SEED + 1)
    # Build an email pool so cards/emails repeat (realistic, DP-friendly).
    pool = []
    for i in range(pool_size):
        first = rng.choice(FIRST_NAMES_EN)
        last = rng.choice(LAST_NAMES_EN)
        pool.append(f"{ascii_slug(first)}.{ascii_slug(last)}{i}@shop.example")

    path = HERE / "transactions_large.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["txn_id", "account_email", "card_number", "txn_date",
                    "merchant_category", "amount_usd", "country"])
        d_start = dt.date(2025, 1, 1)
        d_end = dt.date(2026, 4, 12)
        for i in range(1, n + 1):
            email = rng.choice(pool)
            card = rng.choice(TEST_CARDS)
            date = random_date(rng, d_start, d_end).isoformat()
            cat_item = weighted_choice(rng, MERCHANT_CATEGORIES)
            cat, _w, (lo, hi) = cat_item
            # Log-normal-ish amounts so DP ranges are interesting.
            amount = round(rng.uniform(lo, hi) * rng.triangular(0.6, 1.8, 1.0), 2)
            country = rng.choices(
                [c for c, _ in COUNTRIES],
                weights=[w for _, w in COUNTRIES], k=1)[0]
            w.writerow([f"T-{i:07d}", email, card, date, cat, amount, country])


# --- customers_large.csv (mixed EN + Traditional Chinese) ------------------

def gen_customers(n: int = 500) -> None:
    rng = random.Random(SEED + 2)
    path = HERE / "customers_large.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "姓名", "email", "電話", "城市", "住址",
                    "郵遞區號", "birthdate", "membership_tier",
                    "lifetime_value"])
        dob_start = dt.date(1960, 1, 1)
        dob_end = dt.date(2005, 12, 31)
        for i in range(1, n + 1):
            is_tw = rng.random() < 0.6
            if is_tw:
                last = rng.choice(LAST_NAMES_TW)
                first = rng.choice(FIRST_NAMES_TW)
                full = f"{last}{first}"
                email_user = ascii_slug(first)
                phone = phone_tw(rng)
                city, street, zipc = rng.choice(TW_CITIES)
            else:
                fn = rng.choice(FIRST_NAMES_EN)
                ln = rng.choice(LAST_NAMES_EN)
                full = f"{fn} {ln}"
                email_user = f"{ascii_slug(fn)}.{ascii_slug(ln)}"
                phone = phone_us(rng)
                city = rng.choice(["San Francisco", "New York", "Boston", "Chicago"])
                street = f"{rng.randint(100, 9999)} Market St"
                zipc = rng.choice(SF_ZIPS + NYC_ZIPS)
            tier = rng.choices(
                ["bronze", "silver", "gold", "platinum"],
                weights=[0.4, 0.3, 0.2, 0.1], k=1)[0]
            ltv_mean = {"bronze": 5_000, "silver": 15_000,
                        "gold": 45_000, "platinum": 120_000}[tier]
            ltv = round(normal_clamped(rng, ltv_mean, ltv_mean * 0.25,
                                       0, 300_000))
            w.writerow([
                f"C{i:07d}", full,
                f"{email_user}{i}@example.tw" if is_tw else f"{email_user}{i}@shop.example",
                phone, city, street, zipc,
                random_date(rng, dob_start, dob_end).isoformat(),
                tier, ltv,
            ])


# --- access_logs_large.txt -------------------------------------------------

def gen_access_logs(n: int = 3000, users: int = 200) -> None:
    rng = random.Random(SEED + 3)
    path = HERE / "access_logs_large.txt"
    emails = []
    for i in range(users):
        first = rng.choice(FIRST_NAMES_EN)
        last = rng.choice(LAST_NAMES_EN)
        emails.append(f"{ascii_slug(first)}.{ascii_slug(last)}{i}@acme.example")

    with path.open("w", encoding="utf-8") as f:
        f.write("timestamp|user_email|src_ip|path|status|bytes|user_agent\n")
        base = dt.datetime(2026, 3, 1, 0, 0, 0)
        for i in range(n):
            ts = base + dt.timedelta(seconds=rng.randint(0, 31 * 24 * 3600))
            email = rng.choice(emails)
            ip = f"10.{rng.randint(0, 2)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
            path_ = rng.choice(PATHS)
            status = rng.choices([200, 201, 301, 400, 403, 404, 500],
                                 weights=[70, 5, 3, 6, 4, 8, 4], k=1)[0]
            nbytes = rng.randint(80, 8000) if status < 400 else rng.randint(60, 200)
            ua = rng.choice(UAS)
            f.write(f"{ts.isoformat()}Z|{email}|{ip}|{path_}|{status}|{nbytes}|{ua}\n")


# --- users_large.sql -------------------------------------------------------

def gen_sql(n: int = 500) -> None:
    rng = random.Random(SEED + 4)
    path = HERE / "users_large.sql"
    plans = rng.choices(["free", "pro", "enterprise"],
                        weights=[0.6, 0.3, 0.1], k=n)
    with path.open("w", encoding="utf-8") as f:
        f.write("-- Large SDSA SQL sample (single-table dump).\n")
        f.write("CREATE TABLE IF NOT EXISTS users (\n"
                "  user_id VARCHAR(16) PRIMARY KEY,\n"
                "  email VARCHAR(255) NOT NULL,\n"
                "  phone VARCHAR(32),\n"
                "  full_name VARCHAR(128),\n"
                "  date_of_birth DATE,\n"
                "  zip_code VARCHAR(16),\n"
                "  signup_date DATE,\n"
                "  plan VARCHAR(16)\n"
                ");\n\n")
        # One big INSERT with multi-row VALUES.
        f.write("INSERT INTO users (user_id, email, phone, full_name, "
                "date_of_birth, zip_code, signup_date, plan) VALUES\n")
        dob_start = dt.date(1970, 1, 1)
        dob_end = dt.date(2003, 12, 31)
        signup_start = dt.date(2020, 1, 1)
        signup_end = dt.date(2026, 4, 12)
        lines = []
        for i in range(1, n + 1):
            first = rng.choice(FIRST_NAMES_EN)
            last = rng.choice(LAST_NAMES_EN).replace("'", "''")
            full = f"{first} {last}"
            email = f"{ascii_slug(first)}.{ascii_slug(last)}{i}@acme.example"
            phone = phone_us(rng)
            dob = random_date(rng, dob_start, dob_end).isoformat()
            zipc = rng.choice(SF_ZIPS + NYC_ZIPS)
            signup = random_date(rng, signup_start, signup_end).isoformat()
            lines.append(
                f"  ('U{i:06d}', '{email}', '{phone}', '{full}', "
                f"'{dob}', '{zipc}', '{signup}', '{plans[i-1]}')"
            )
        f.write(",\n".join(lines))
        f.write(";\n")


def gen_employees_huge(target_bytes: int = 200 * 1024 * 1024) -> None:
    """Generate a ~target_bytes CSV by streaming rows until the file is large enough.

    Uses the same schema as employees_large.csv but scales to hundreds of MB
    for load-testing the pipeline. Writes in chunks for speed.
    """
    rng = random.Random(SEED + 10)
    path = HERE / "employees_huge.csv"
    zips = SF_ZIPS + NYC_ZIPS
    dob_start = dt.date(1960, 1, 1)
    dob_end = dt.date(2003, 12, 31)
    hire_start = dt.date(2005, 1, 1)
    hire_end = dt.date(2025, 12, 31)

    header = ("employee_id,full_name,email,phone,dob,zip,department,"
              "job_title,salary,hire_date\n")

    # Buffer rows in memory and flush periodically — a lot faster than csv.writer
    # for this row size.
    chunk_rows = 10_000
    buf: list[str] = []
    written = 0
    i = 0
    with path.open("w", encoding="utf-8") as f:
        f.write(header)
        written += len(header)
        while written < target_bytes:
            i += 1
            first = rng.choice(FIRST_NAMES_EN)
            last = rng.choice(LAST_NAMES_EN).replace(",", "").replace("\"", "")
            full = f"{first} {last}"
            email = f"{ascii_slug(first)}.{ascii_slug(last)}{i}@acme.example"
            phone = phone_us(rng)
            dob = random_date(rng, dob_start, dob_end).isoformat()
            z = rng.choice(zips)
            dept, _wt, (sal_mean, sal_sd) = weighted_choice(rng, DEPARTMENTS)
            title = rng.choice(TITLES[dept])
            salary = round(normal_clamped(rng, sal_mean, sal_sd, 40_000, 300_000))
            hire = random_date(rng, hire_start, hire_end).isoformat()
            # Some titles legitimately have commas; quote the name/title fields.
            line = (f"E{i:08d},\"{full}\",{email},{phone},{dob},{z},"
                    f"{dept},\"{title}\",{salary},{hire}\n")
            buf.append(line)
            if len(buf) >= chunk_rows:
                chunk = "".join(buf)
                f.write(chunk)
                written += len(chunk)
                buf.clear()
        if buf:
            chunk = "".join(buf)
            f.write(chunk)
            written += len(chunk)


def main() -> None:
    import sys
    huge = "--huge" in sys.argv or "--all" in sys.argv

    gen_employees(1000)
    gen_transactions(5000)
    gen_customers(500)
    gen_access_logs(3000)
    gen_sql(500)

    if huge:
        print("generating huge sample (~200 MB) — this takes a minute…", flush=True)
        gen_employees_huge(200 * 1024 * 1024)

    print("wrote:")
    for p in sorted(list(HERE.glob("*_large.*")) + list(HERE.glob("*_huge.*"))):
        size = p.stat().st_size
        mb = size / (1024 * 1024)
        print(f"  {p.name:28s} {size:>12,} bytes ({mb:>6.1f} MB)")


if __name__ == "__main__":
    main()
