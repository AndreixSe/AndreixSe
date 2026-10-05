import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

DB_PATH = "/data/pontaj.db"
if not os.path.exists("/data"):
    DB_PATH = "pontaj.db"

def get_db():

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    return conn


def migrate_database():

    conn = get_db()
    cur = conn.cursor()

    # -----------------------------------------------------
    # SETTINGS
    # MIGRARE AUTOMATĂ DIN VECHIUL FORMAT
    # -----------------------------------------------------

    cur.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name = 'settings'
    """)

    settings_exists = cur.fetchone() is not None

    if not settings_exists:

        # Nu există deloc tabelul.
        # Îl creăm direct în formatul nou.

        cur.execute("""
            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        print("✅ Tabelul settings a fost creat.")

    else:

        # Verificăm structura tabelului existent.

        cur.execute("PRAGMA table_info(settings)")

        settings_columns = [
            row["name"]
            for row in cur.fetchall()
        ]

        # Dacă NU există coloana key,
        # înseamnă că avem vechiul tabel:
        #
        # guild_id
        # report_channel_id
        #
        # Îl migrăm automat.

        if "key" not in settings_columns:

            print(
                "⚠️ A fost detectat vechiul tabel settings."
            )

            # Alegem un nume de backup care nu există deja.

            backup_table = "settings_old"
            counter = 1

            while True:

                cur.execute("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    AND name = ?
                """, (backup_table,))

                if cur.fetchone() is None:
                    break

                backup_table = f"settings_old_{counter}"
                counter += 1

            # Păstrăm tabelul vechi ca backup.

            cur.execute(
                f'ALTER TABLE settings RENAME TO "{backup_table}"'
            )

            print(
                f"✅ Vechiul settings a fost păstrat ca "
                f"{backup_table}."
            )

            # Creăm noul tabel.

            cur.execute("""
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Verificăm ce coloane avea vechiul tabel.

            cur.execute(
                f'PRAGMA table_info("{backup_table}")'
            )

            old_settings_columns = [
                row["name"]
                for row in cur.fetchall()
            ]

            # Dacă vechiul tabel avea report_channel_id,
            # îl mutăm în noul sistem pentru pontaj.

            if "report_channel_id" in old_settings_columns:

                cur.execute(
                    f'''
                    SELECT report_channel_id
                    FROM "{backup_table}"
                    LIMIT 1
                    '''
                )

                old_report_channel = cur.fetchone()

                if (
                    old_report_channel
                    and old_report_channel["report_channel_id"]
                ):

                    cur.execute("""
                        INSERT OR REPLACE INTO settings(
                            key,
                            value
                        )
                        VALUES (?, ?)
                    """, (
                        "attendance_panel_channel_id",
                        str(
                            old_report_channel[
                                "report_channel_id"
                            ]
                        )
                    ))

                    print(
                        "✅ report_channel_id a fost migrat "
                        "în attendance_panel_channel_id."
                    )

            print(
                "✅ Tabelul settings a fost migrat automat."
            )

        else:

            print(
                "✅ Tabelul settings este deja în format nou."
            )

    # -----------------------------------------------------
    # ATTENDANCE
    # -----------------------------------------------------

    # -----------------------------------------------------
    # ATTENDANCE + ATTENDANCE HISTORY
    # Migrare robustă din schemele legacy.
    # Reconstruim tabelele dacă există coloane obligatorii vechi
    # (ex: session_id, display_name) care blochează INSERT-urile noi.
    # Tabelele vechi sunt păstrate automat ca backup.
    # -----------------------------------------------------

    def _table_exists(table_name):
        cur.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
        """, (table_name,))
        return cur.fetchone() is not None

    def _unique_backup_name(base_name):
        name = base_name
        counter = 1
        while _table_exists(name):
            name = f"{base_name}_{counter}"
            counter += 1
        return name

    # ---------------- ATTENDANCE ----------------

    if not _table_exists("attendance"):
        cur.execute("""
            CREATE TABLE attendance (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT,
                started_at TEXT
            )
        """)
        print("✅ Tabelul attendance a fost creat.")
    else:
        cur.execute("PRAGMA table_info(attendance)")
        attendance_info = cur.fetchall()
        attendance_columns = [row["name"] for row in attendance_info]

        attendance_target = {"user_id", "user_name", "started_at"}

        attendance_has_blocking_legacy = any(
            row["name"] not in attendance_target
            and row["notnull"] == 1
            and row["dflt_value"] is None
            for row in attendance_info
        )

        attendance_missing_core = (
            "user_id" not in attendance_columns
            or "started_at" not in attendance_columns
        )

        if attendance_has_blocking_legacy or attendance_missing_core:
            backup = _unique_backup_name("attendance_legacy_backup")

            cur.execute(
                f'ALTER TABLE attendance RENAME TO "{backup}"'
            )

            cur.execute("""
                CREATE TABLE attendance (
                    user_id INTEGER PRIMARY KEY,
                    user_name TEXT,
                    started_at TEXT
                )
            """)

            cur.execute(f'PRAGMA table_info("{backup}")')
            old_columns = [row["name"] for row in cur.fetchall()]

            def _expr(preferred, fallback=None, default="NULL"):
                if preferred in old_columns:
                    return f'"{preferred}"'
                if fallback and fallback in old_columns:
                    return f'"{fallback}"'
                return default

            uid = _expr("user_id")
            uname = _expr("user_name", "display_name")
            started = _expr("started_at")

            # user_id este cheia primară în schema nouă. INSERT OR IGNORE
            # păstrează o singură sesiune activă per utilizator dacă vechiul
            # tabel conține duplicate.
            cur.execute(f"""
                INSERT OR IGNORE INTO attendance(
                    user_id,
                    user_name,
                    started_at
                )
                SELECT
                    {uid},
                    {uname},
                    {started}
                FROM "{backup}"
                WHERE {uid} IS NOT NULL
            """)

            print(
                "✅ attendance a fost migrat la schema nouă. "
                f"Backup: {backup}"
            )
        else:
            if "user_name" not in attendance_columns:
                cur.execute("""
                    ALTER TABLE attendance
                    ADD COLUMN user_name TEXT
                """)

    # Normalizăm timestamp-urile active.
    cur.execute("""
        SELECT user_id, started_at
        FROM attendance
        WHERE started_at IS NOT NULL
    """)
    for row in cur.fetchall():
        formatted = format_timestamp(row["started_at"])
        if formatted != row["started_at"]:
            cur.execute("""
                UPDATE attendance
                SET started_at = ?
                WHERE user_id = ?
            """, (formatted, row["user_id"]))

    # ---------------- ATTENDANCE HISTORY ----------------

    if not _table_exists("attendance_history"):
        cur.execute("""
            CREATE TABLE attendance_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_name TEXT,
                started_at TEXT,
                ended_at TEXT
            )
        """)
        print("✅ Tabelul attendance_history a fost creat.")
    else:
        cur.execute("PRAGMA table_info(attendance_history)")
        history_info = cur.fetchall()
        history_columns = [row["name"] for row in history_info]

        history_target = {
            "id", "user_id", "user_name", "started_at", "ended_at"
        }

        history_has_blocking_legacy = any(
            row["name"] not in history_target
            and row["notnull"] == 1
            and row["dflt_value"] is None
            for row in history_info
        )

        history_missing_core = (
            "user_id" not in history_columns
            or "started_at" not in history_columns
            or "ended_at" not in history_columns
        )

        if history_has_blocking_legacy or history_missing_core:
            backup = _unique_backup_name(
                "attendance_history_legacy_backup"
            )

            cur.execute(
                f'ALTER TABLE attendance_history RENAME TO "{backup}"'
            )

            cur.execute("""
                CREATE TABLE attendance_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_name TEXT,
                    started_at TEXT,
                    ended_at TEXT
                )
            """)

            cur.execute(f'PRAGMA table_info("{backup}")')
            old_columns = [row["name"] for row in cur.fetchall()]

            def _hexpr(preferred, fallback=None, default="NULL"):
                if preferred in old_columns:
                    return f'"{preferred}"'
                if fallback and fallback in old_columns:
                    return f'"{fallback}"'
                return default

            uid = _hexpr("user_id")
            uname = _hexpr("user_name", "display_name")
            started = _hexpr("started_at")
            ended = _hexpr("ended_at")

            cur.execute(f"""
                INSERT INTO attendance_history(
                    user_id,
                    user_name,
                    started_at,
                    ended_at
                )
                SELECT
                    {uid},
                    {uname},
                    {started},
                    {ended}
                FROM "{backup}"
            """)

            print(
                "✅ attendance_history a fost migrat la schema nouă. "
                f"Backup: {backup}"
            )
        else:
            if "user_name" not in history_columns:
                cur.execute("""
                    ALTER TABLE attendance_history
                    ADD COLUMN user_name TEXT
                """)

    # Normalizăm timestamp-urile din istoric.
    cur.execute("""
        SELECT id, started_at, ended_at
        FROM attendance_history
    """)
    for row in cur.fetchall():
        formatted_started = format_timestamp(row["started_at"])
        formatted_ended = format_timestamp(row["ended_at"])

        if (
            formatted_started != row["started_at"]
            or formatted_ended != row["ended_at"]
        ):
            cur.execute("""
                UPDATE attendance_history
                SET started_at = ?, ended_at = ?
                WHERE id = ?
            """, (
                formatted_started,
                formatted_ended,
                row["id"]
            ))

    # -----------------------------------------------------
    # PATROLS
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS patrols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            people_count INTEGER DEFAULT 0,
            cars_count INTEGER DEFAULT 0,
            color TEXT,
            patrol_date TEXT,
            patrol_time TEXT,
            image_url TEXT,
            started_at TEXT,
            ended_at TEXT,
            created_by_id INTEGER,
            created_by_name TEXT,
            active INTEGER DEFAULT 1,
            session_id TEXT,
            message_id TEXT
        )
    """)

    cur.execute("PRAGMA table_info(patrols)")

    patrol_columns = [
        row["name"]
        for row in cur.fetchall()
    ]

    patrol_migrations = {
        "name": "TEXT",
        "people_count": "INTEGER DEFAULT 0",
        "cars_count": "INTEGER DEFAULT 0",
        "color": "TEXT",
        "patrol_date": "TEXT",
        "patrol_time": "TEXT",
        "image_url": "TEXT",
        "started_at": "TEXT",
        "ended_at": "TEXT",
        "created_by_id": "INTEGER",
        "created_by_name": "TEXT",
        "active": "INTEGER DEFAULT 1",
        "session_id": "TEXT",
        "message_id": "TEXT",
    }

    for column, column_type in patrol_migrations.items():

        if column not in patrol_columns:

            cur.execute(
                f"ALTER TABLE patrols ADD COLUMN {column} {column_type}"
            )

    # -----------------------------------------------------
    # PATROL PEOPLE
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS patrol_people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrol_id INTEGER,
            user_id INTEGER,
            user_name TEXT,
            display_name TEXT,
            mention TEXT
        )
    """)

    cur.execute("PRAGMA table_info(patrol_people)")

    patrol_people_columns = [
        row["name"]
        for row in cur.fetchall()
    ]

    if "user_name" not in patrol_people_columns:

        cur.execute("""
            ALTER TABLE patrol_people
            ADD COLUMN user_name TEXT
        """)

    if "display_name" not in patrol_people_columns:

        cur.execute("""
            ALTER TABLE patrol_people
            ADD COLUMN display_name TEXT
        """)

    if "mention" not in patrol_people_columns:

        cur.execute("""
            ALTER TABLE patrol_people
            ADD COLUMN mention TEXT
        """)

    # -----------------------------------------------------
    # UMPLEREA DATELOR VECHI
    # -----------------------------------------------------

    cur.execute("""
        UPDATE patrol_people
        SET user_name = display_name
        WHERE user_name IS NULL
        AND display_name IS NOT NULL
    """)

    cur.execute("""
        UPDATE patrol_people
        SET display_name = user_name
        WHERE display_name IS NULL
        AND user_name IS NOT NULL
    """)

    cur.execute("""
        UPDATE patrol_people
        SET mention = '<@' || user_id || '>'
        WHERE mention IS NULL
        AND user_id IS NOT NULL
    """)

    # -----------------------------------------------------
    # DONATIONS
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            donor_id INTEGER,
            donor_name TEXT,
            items TEXT,
            items_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            confirmed_at TEXT,
            confirmed_by_id INTEGER,
            confirmed_by_name TEXT,
            session_id TEXT
        )
    """)

    cur.execute("PRAGMA table_info(donations)")
    donation_columns = [
        row["name"]
        for row in cur.fetchall()
    ]

    if "session_id" not in donation_columns:
        cur.execute("""
            ALTER TABLE donations
            ADD COLUMN session_id TEXT
        """)

    # -----------------------------------------------------
    # DEFAULT SETTINGS
    # -----------------------------------------------------

    defaults = {
        "patrol_panel_channel_id": "",
        "patrol_panel_message_id": "",
        "patrol_session_id": "",

        "attendance_panel_channel_id": "",
        "attendance_panel_message_id": "",

        "donation_panel_channel_id": "",
        "donation_panel_message_id": "",
        "donation_session_id": "",
    }

    for key, value in defaults.items():

        cur.execute("""
            INSERT OR IGNORE INTO settings(key, value)
            VALUES (?, ?)
        """, (key, value))

    conn.commit()
    conn.close()

    print("========================================")
    print("✅ Baza de date verificata si migrata.")
    print("========================================")


# =========================================================
# SETTINGS
# =========================================================

def get_setting(key):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    )

    row = cur.fetchone()

    conn.close()

    if row:
        return row["value"]

    return None


def set_setting(key, value):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
    """, (key, value))

    conn.commit()
    conn.close()


# =========================================================
# TIME
# =========================================================

def now():

    return datetime.now(ZoneInfo("Europe/Bucharest"))


def now_string():

    return now().strftime("%d.%m.%Y %H:%M:%S")


def format_timestamp(value):
    """
    Normalizează atât timestamp-urile noi (DD.MM.YYYY HH:MM:SS),
    cât și timestamp-urile ISO rămase din versiuni vechi ale botului.
    """
    if not value:
        return value

    value = str(value).strip()

    # Deja este în formatul dorit.
    try:
        parsed = datetime.strptime(value, "%d.%m.%Y %H:%M:%S")
        return parsed.strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        pass

    # Timestamp ISO vechi, inclusiv cu timezone.
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        return value
