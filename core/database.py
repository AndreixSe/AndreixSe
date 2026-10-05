import os
import sqlite3
from datetime import datetime

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            user_id INTEGER PRIMARY KEY,
            user_name TEXT,
            started_at TEXT
        )
    """)

    # Migrare automată pentru versiuni vechi ale tabelului attendance.
    cur.execute("PRAGMA table_info(attendance)")
    attendance_columns = [
        row["name"]
        for row in cur.fetchall()
    ]

    if "user_name" not in attendance_columns:
        cur.execute("""
            ALTER TABLE attendance
            ADD COLUMN user_name TEXT
        """)
        print("✅ Coloana attendance.user_name a fost adăugată.")

    if "started_at" not in attendance_columns:
        cur.execute("""
            ALTER TABLE attendance
            ADD COLUMN started_at TEXT
        """)
        print("✅ Coloana attendance.started_at a fost adăugată.")

    # Convertim timestamp-urile vechi ISO în formatul nou.
    cur.execute("""
        SELECT user_id, started_at
        FROM attendance
        WHERE started_at IS NOT NULL
    """)

    old_attendance_rows = cur.fetchall()

    for row in old_attendance_rows:
        formatted = format_timestamp(row["started_at"])

        if formatted != row["started_at"]:
            cur.execute("""
                UPDATE attendance
                SET started_at = ?
                WHERE user_id = ?
            """, (
                formatted,
                row["user_id"]
            ))

    # -----------------------------------------------------
    # ATTENDANCE HISTORY
    # Migrare robustă din schema veche către schema modulară.
    # Păstrăm tabelul vechi ca backup înainte de conversie.
    # -----------------------------------------------------

    cur.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name = 'attendance_history'
    """)

    history_exists = cur.fetchone() is not None

    if not history_exists:

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

        history_columns = [
            row["name"]
            for row in history_info
        ]

        # Schema țintă a sistemului modular.
        target_columns = {
            "id",
            "user_id",
            "user_name",
            "started_at",
            "ended_at",
        }

        # Dacă există coloane legacy obligatorii (de ex. session_id,
        # display_name) sau lipsesc coloane din schema nouă, reconstruim
        # tabelul. SQLite nu poate elimina simplu constrângeri NOT NULL.
        has_legacy_required_columns = any(
            row["name"] not in target_columns
            and row["notnull"] == 1
            and row["dflt_value"] is None
            for row in history_info
        )

        missing_target_columns = any(
            column not in history_columns
            for column in ("user_id", "user_name", "started_at", "ended_at")
        )

        if has_legacy_required_columns or missing_target_columns:

            backup_table = "attendance_history_legacy_backup"
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

                backup_table = (
                    f"attendance_history_legacy_backup_{counter}"
                )
                counter += 1

            cur.execute(
                f'ALTER TABLE attendance_history '
                f'RENAME TO "{backup_table}"'
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

            cur.execute(
                f'PRAGMA table_info("{backup_table}")'
            )

            old_columns = [
                row["name"]
                for row in cur.fetchall()
            ]

            def old_expr(preferred, fallback=None, default="NULL"):
                if preferred in old_columns:
                    return f'"{preferred}"'
                if fallback and fallback in old_columns:
                    return f'"{fallback}"'
                return default

            user_id_expr = old_expr("user_id")
            user_name_expr = old_expr(
                "user_name",
                fallback="display_name"
            )
            started_at_expr = old_expr("started_at")
            ended_at_expr = old_expr("ended_at")

            cur.execute(f"""
                INSERT INTO attendance_history(
                    user_id,
                    user_name,
                    started_at,
                    ended_at
                )
                SELECT
                    {user_id_expr},
                    {user_name_expr},
                    {started_at_expr},
                    {ended_at_expr}
                FROM "{backup_table}"
            """)

            print(
                "✅ attendance_history a fost migrat la schema nouă. "
                f"Backup: {backup_table}"
            )

        else:

            # Schema este deja compatibilă. Adăugăm doar coloanele
            # opționale lipsă, dacă este cazul.
            if "user_name" not in history_columns:
                cur.execute("""
                    ALTER TABLE attendance_history
                    ADD COLUMN user_name TEXT
                """)

            if "started_at" not in history_columns:
                cur.execute("""
                    ALTER TABLE attendance_history
                    ADD COLUMN started_at TEXT
                """)

            if "ended_at" not in history_columns:
                cur.execute("""
                    ALTER TABLE attendance_history
                    ADD COLUMN ended_at TEXT
                """)

    # Normalizăm timestamp-urile după migrare.
    cur.execute("""
        SELECT id, started_at, ended_at
        FROM attendance_history
    """)

    old_history_rows = cur.fetchall()

    for row in old_history_rows:

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
            active INTEGER DEFAULT 1
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
            confirmed_by_name TEXT
        )
    """)

    # -----------------------------------------------------
    # DEFAULT SETTINGS
    # -----------------------------------------------------

    defaults = {
        "patrol_panel_channel_id": "",
        "patrol_panel_message_id": "",

        "attendance_panel_channel_id": "",
        "attendance_panel_message_id": "",

        "donation_panel_channel_id": "",
        "donation_panel_message_id": "",
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

    return datetime.now()


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
