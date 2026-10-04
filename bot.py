import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


# =========================================================
# CONFIGURARE
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Bucharest")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN lipsește din variabilele de mediu."
    )

try:
    TZ = ZoneInfo(TIMEZONE_NAME)
except Exception:
    TZ = ZoneInfo("Europe/Bucharest")


# =========================================================
# DATABASE
# =========================================================

if os.path.isdir("/data"):
    DB_FILE = "/data/pontaj.db"
else:
    DB_FILE = "pontaj.db"


# =========================================================
# BOT
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# =========================================================
# DATABASE MIGRATION
# =========================================================

def migrate_database(conn):

    cur = conn.cursor()

    # =====================================================
    # MIGRARE SETTINGS
    # =====================================================

    cur.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'settings'
    """)

    settings_exists = cur.fetchone()

    if settings_exists:

        cur.execute(
            "PRAGMA table_info(settings)"
        )

        columns = cur.fetchall()

        column_names = [
            column["name"]
            for column in columns
        ]

        if "key" not in column_names:

            print(
                "Baza de date veche pentru settings a fost detectată."
            )

            print(
                "Se reconstruiește tabelul settings..."
            )

            cur.execute("""
                ALTER TABLE settings
                RENAME TO settings_old
            """)

            cur.execute("""
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            cur.execute("""
                PRAGMA table_info(settings_old)
            """)

            old_columns = cur.fetchall()

            old_column_names = [
                column["name"]
                for column in old_columns
            ]

            if (
                "name" in old_column_names
                and "value" in old_column_names
            ):

                try:

                    cur.execute("""
                        INSERT OR IGNORE INTO settings (
                            key,
                            value
                        )
                        SELECT
                            name,
                            value
                        FROM settings_old
                    """)

                    print(
                        "Setările vechi au fost migrate."
                    )

                except Exception as e:

                    print(
                        f"Nu am putut migra setările vechi: {e}"
                    )

            elif (
                "setting" in old_column_names
                and "value" in old_column_names
            ):

                try:

                    cur.execute("""
                        INSERT OR IGNORE INTO settings (
                            key,
                            value
                        )
                        SELECT
                            setting,
                            value
                        FROM settings_old
                    """)

                    print(
                        "Setările vechi au fost migrate."
                    )

                except Exception as e:

                    print(
                        f"Nu am putut migra setările vechi: {e}"
                    )

            else:

                print(
                    "Structura veche settings nu poate fi migrată."
                )

            cur.execute("""
                DROP TABLE settings_old
            """)

            print(
                "Tabelul settings a fost migrat."
            )

    # =====================================================
    # MIGRARE ATTENDANCE
    # =====================================================

    cur.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'attendance'
    """)

    attendance_exists = cur.fetchone()

    if attendance_exists:

        cur.execute(
            "PRAGMA table_info(attendance)"
        )

        columns = cur.fetchall()

        column_names = [
            column["name"]
            for column in columns
        ]

        required_columns = [
            "id",
            "session_id",
            "user_id",
            "display_name",
            "avatar_url",
            "started_at"
        ]

        attendance_is_correct = all(
            column in column_names
            for column in required_columns
        )

        if not attendance_is_correct:

            print(
                "Baza de date veche pentru attendance a fost detectată."
            )

            print(
                "Se reconstruiește tabelul attendance..."
            )

            cur.execute("""
                ALTER TABLE attendance
                RENAME TO attendance_old
            """)

            cur.execute("""
                CREATE TABLE attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    display_name TEXT NOT NULL,
                    avatar_url TEXT,
                    started_at TEXT NOT NULL,
                    UNIQUE(session_id, user_id)
                )
            """)

            print(
                "Tabelul attendance nou a fost creat."
            )

            print(
                "Datele vechi de attendance nu sunt compatibile "
                "cu structura nouă și vor fi eliminate."
            )

            cur.execute("""
                DROP TABLE attendance_old
            """)

            print(
                "Tabelul attendance vechi a fost eliminat."
            )

    # =====================================================
    # MIGRARE HISTORY
    # =====================================================

    cur.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'attendance_history'
    """)

    history_exists = cur.fetchone()

    if history_exists:

        cur.execute(
            "PRAGMA table_info(attendance_history)"
        )

        columns = cur.fetchall()

        column_names = [
            column["name"]
            for column in columns
        ]

        required_history_columns = [
            "id",
            "session_id",
            "user_id",
            "display_name",
            "avatar_url",
            "started_at",
            "ended_at"
        ]

        history_is_correct = all(
            column in column_names
            for column in required_history_columns
        )

        if not history_is_correct:

            print(
                "Structura veche pentru attendance_history a fost detectată."
            )

            cur.execute("""
                DROP TABLE attendance_history
            """)

            print(
                "Tabelul attendance_history vechi a fost eliminat."
            )


# =========================================================
# INITIALIZARE DATABASE
# =========================================================

def init_db():

    conn = get_db()

    migrate_database(conn)

    cur = conn.cursor()

    # =====================================================
    # ATTENDANCE ACTIV
    # =====================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            avatar_url TEXT,
            started_at TEXT NOT NULL,
            UNIQUE(session_id, user_id)
        )
    """)

    # =====================================================
    # ISTORIC
    # =====================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            avatar_url TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT
        )
    """)

    # =====================================================
    # SETTINGS
    # =====================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # =====================================================
    # DEFAULT SETTINGS
    # =====================================================

    cur.execute("""
        INSERT OR IGNORE INTO settings (
            key,
            value
        )
        VALUES (
            'session_id',
            '0'
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO settings (
            key,
            value
        )
        VALUES (
            'session_active',
            '0'
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO settings (
            key,
            value
        )
        VALUES (
            'panel_channel_id',
            ''
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO settings (
            key,
            value
        )
        VALUES (
            'panel_message_id',
            ''
        )
    """)

    conn.commit()
    conn.close()

    print(
        "Database inițializată cu succes."
    )


# =========================================================
# SETTINGS
# =========================================================

def get_setting(
    key,
    default=None
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT value
        FROM settings
        WHERE key = ?
        """,
        (key,)
    )

    row = cur.fetchone()

    conn.close()

    if row is None:
        return default

    return row["value"]


def set_setting(
    key,
    value
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO settings (
            key,
            value
        )
        VALUES (
            ?,
            ?
        )
        ON CONFLICT(key)
        DO UPDATE SET
            value = excluded.value
    """, (
        key,
        str(value)
    ))

    conn.commit()
    conn.close()


# =========================================================
# SESSION
# =========================================================

def get_current_session_id():

    return int(
        get_setting(
            "session_id",
            "0"
        )
    )


def is_session_active():

    return (
        get_setting(
            "session_active",
            "0"
        ) == "1"
    )


# =========================================================
# TIME
# =========================================================

def now_local():

    return datetime.now(TZ)


def parse_datetime(value):

    try:

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=TZ
            )

        return dt.astimezone(TZ)

    except Exception:

        return None


def format_time(value):

    dt = parse_datetime(value)

    if dt is None:

        return "--:--"

    return dt.strftime(
        "%H:%M"
    )


def calculate_duration(
    started_at,
    ended_at
):

    start = parse_datetime(
        started_at
    )

    end = parse_datetime(
        ended_at
    )

    if start is None:

        return timedelta(0)

    if end is None:

        end = now_local()

    duration = end - start

    if duration.total_seconds() < 0:

        return timedelta(0)

    return duration


def format_duration(
    duration
):

    total_seconds = int(
        duration.total_seconds()
    )

    hours = total_seconds // 3600

    minutes = (
        total_seconds % 3600
    ) // 60

    if hours > 0:

        return f"{hours}h {minutes}m"

    return f"{minutes}m"


# =========================================================
# ACTIVE USERS
# =========================================================

def get_present_users():

    session_id = get_current_session_id()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM attendance
        WHERE session_id = ?
        ORDER BY id ASC
    """, (
        session_id,
    ))

    rows = cur.fetchall()

    conn.close()

    return rows


# =========================================================
# PANEL EMBED
# =========================================================

def create_panel_embed(
    session_finished=False
):

    if session_finished:

        embed = discord.Embed(
            title="🔴 PREZENȚĂ",
            description=(
                "Sesiunea de prezență este încheiată."
            ),
            color=discord.Color.red()
        )

    else:

        embed = discord.Embed(
            title="🟢 PREZENȚĂ",
            description=(
                "Apasă **🟢 PREZENT** pentru a intra "
                "în lista persoanelor prezente.\n\n"
                "Apasă **🔴 PLECARE** când pleci."
            ),
            color=discord.Color.green()
        )

    users = get_present_users()

    if not users:

        embed.add_field(
            name="👥 Persoane prezente",
            value="Nimeni nu este prezent.",
            inline=False
        )

    else:

        lines = [
            "```",
            "#   NUME                         ORA",
            "────────────────────────────────────"
        ]

        for index, user in enumerate(
            users,
            start=1
        ):

            name = user["display_name"]

            if len(name) > 24:

                name = (
                    name[:21]
                    + "..."
                )

            ora = format_time(
                user["started_at"]
            )

            lines.append(
                f"{index:<3} {name:<28} {ora}"
            )

        lines.append(
            "```"
        )

        embed.add_field(
            name=f"👥 Prezenți: {len(users)}",
            value="\n".join(lines),
            inline=False
        )

    if users and len(users) <= 5:

        avatar_names = []

        for user in users:

            if user["avatar_url"]:

                avatar_names.append(
                    f"🟢 {user['display_name']}"
                )

        if avatar_names:

            embed.add_field(
                name="📸 Persoane prezente",
                value="\n".join(
                    avatar_names
                ),
                inline=False
            )

    if session_finished:

        embed.set_footer(
            text="Sesiunea este închisă."
        )

    else:

        embed.set_footer(
            text="Lista se actualizează automat."
        )

    return embed


# =========================================================
# HISTORY
# =========================================================

def get_history():

    session_id = get_current_session_id()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM attendance_history
        WHERE session_id = ?
        ORDER BY id ASC
    """, (
        session_id,
    ))

    rows = cur.fetchall()

    conn.close()

    return rows


# =========================================================
# HISTORY GROUPING
# =========================================================

def group_history(rows):

    grouped = {}

    for row in rows:

        user_id = row["user_id"]

        if user_id not in grouped:

            grouped[user_id] = {
                "user_id": user_id,
                "display_name": row["display_name"],
                "avatar_url": row["avatar_url"],
                "periods": [],
                "total": timedelta(0)
            }

        start = row["started_at"]
        end = row["ended_at"]

        grouped[user_id]["periods"].append(
            (
                start,
                end
            )
        )

        grouped[user_id]["total"] += (
            calculate_duration(
                start,
                end
            )
        )

    return list(
        grouped.values()
    )


# =========================================================
# PRESENCE VIEW
# =========================================================

class PresenceView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    # =====================================================
    # PREZENT
    # =====================================================

    @discord.ui.button(
        label="PREZENT",
        emoji="🟢",
        style=discord.ButtonStyle.success,
        custom_id="pontaj_prezent"
    )
    async def prezent(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_session_active():

            await interaction.response.defer(
                ephemeral=True
            )

            return

        user = interaction.user

        session_id = get_current_session_id()

        avatar_url = None

        if user.display_avatar:

            avatar_url = str(
                user.display_avatar.url
            )

        conn = get_db()
        cur = conn.cursor()

        # =================================================
        # VERIFICĂM DACĂ ESTE DEJA PREZENT
        # =================================================

        cur.execute("""
            SELECT id
            FROM attendance
            WHERE session_id = ?
              AND user_id = ?
        """, (
            session_id,
            user.id
        ))

        existing = cur.fetchone()

        if existing:

            conn.close()

            await interaction.response.defer(
                ephemeral=True
            )

            return

        current_time = now_local().isoformat()

        # =================================================
        # ADĂUGĂM PREZENȚA ACTIVĂ
        # =================================================

        cur.execute("""
            INSERT INTO attendance (
                session_id,
                user_id,
                display_name,
                avatar_url,
                started_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            session_id,
            user.id,
            user.display_name,
            avatar_url,
            current_time
        ))

        # =================================================
        # ADĂUGĂM ȘI ÎN ISTORIC
        # =================================================

        cur.execute("""
            INSERT INTO attendance_history (
                session_id,
                user_id,
                display_name,
                avatar_url,
                started_at,
                ended_at
            )
            VALUES (?, ?, ?, ?, ?, NULL)
        """, (
            session_id,
            user.id,
            user.display_name,
            avatar_url,
            current_time
        ))

        conn.commit()
        conn.close()

        # =================================================
        # FĂRĂ MESAJ
        # =================================================

        await interaction.response.defer(
            ephemeral=True
        )

        await update_panel()

    # =====================================================
    # PLECARE
    # =====================================================

    @discord.ui.button(
        label="PLECARE",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        custom_id="pontaj_plecare"
    )
    async def plecare(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_session_active():

            await interaction.response.defer(
                ephemeral=True
            )

            return

        user = interaction.user

        session_id = get_current_session_id()

        conn = get_db()
        cur = conn.cursor()

        # =================================================
        # VERIFICĂM DACĂ ESTE PREZENT
        # =================================================

        cur.execute("""
            SELECT *
            FROM attendance
            WHERE session_id = ?
              AND user_id = ?
        """, (
            session_id,
            user.id
        ))

        existing = cur.fetchone()

        if not existing:

            conn.close()

            await interaction.response.defer(
                ephemeral=True
            )

            return

        current_time = now_local().isoformat()

        # =================================================
        # GĂSIM ULTIMA INTRARE FĂRĂ IEȘIRE
        # =================================================

        cur.execute("""
            SELECT id
            FROM attendance_history
            WHERE session_id = ?
              AND user_id = ?
              AND ended_at IS NULL
            ORDER BY id DESC
            LIMIT 1
        """, (
            session_id,
            user.id
        ))

        history_row = cur.fetchone()

        if history_row:

            cur.execute("""
                UPDATE attendance_history
                SET ended_at = ?
                WHERE id = ?
            """, (
                current_time,
                history_row["id"]
            ))

        # =================================================
        # ȘTERGEM DIN LISTA ACTIVĂ
        # =================================================

        cur.execute("""
            DELETE FROM attendance
            WHERE session_id = ?
              AND user_id = ?
        """, (
            session_id,
            user.id
        ))

        conn.commit()
        conn.close()

        # =================================================
        # FĂRĂ MESAJ
        # =================================================

        await interaction.response.defer(
            ephemeral=True
        )

        await update_panel()


# =========================================================
# UPDATE PANEL
# =========================================================

async def update_panel():

    channel_id = get_setting(
        "panel_channel_id",
        ""
    )

    message_id = get_setting(
        "panel_message_id",
        ""
    )

    if not channel_id or not message_id:

        return

    try:

        channel = bot.get_channel(
            int(channel_id)
        )

        if channel is None:

            channel = await bot.fetch_channel(
                int(channel_id)
            )

        message = await channel.fetch_message(
            int(message_id)
        )

        await message.edit(
            content=None,
            embed=create_panel_embed(),
            view=PresenceView()
        )

    except discord.NotFound:

        print(
            "Panoul nu mai există în Discord."
        )

    except Exception as e:

        print(
            f"Eroare la actualizarea panoului: {e}"
        )


# =========================================================
# /setup_prezenta
# =========================================================

@bot.tree.command(
    name="setup_prezenta",
    description=(
        "Creează panoul de prezență "
        "și pornește o sesiune nouă."
    )
)
@app_commands.default_permissions(
    administrator=True
)
async def setup_prezenta(
    interaction: discord.Interaction
):

    if not interaction.user.guild_permissions.administrator:

        await interaction.response.send_message(
            "❌ Nu ai permisiunea de Administrator.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    # =====================================================
    # ȘTERGEM PANELUL VECHI
    # =====================================================

    old_channel_id = get_setting(
        "panel_channel_id",
        ""
    )

    old_message_id = get_setting(
        "panel_message_id",
        ""
    )

    if old_channel_id and old_message_id:

        try:

            old_channel = bot.get_channel(
                int(old_channel_id)
            )

            if old_channel is None:

                old_channel = await bot.fetch_channel(
                    int(old_channel_id)
                )

            old_message = await old_channel.fetch_message(
                int(old_message_id)
            )

            await old_message.delete()

            print(
                "Panoul vechi a fost șters."
            )

        except Exception as e:

            print(
                f"Nu am putut șterge panoul vechi: {e}"
            )

    # =====================================================
    # SESIUNE NOUĂ
    # =====================================================

    old_session = get_current_session_id()

    new_session = old_session + 1

    set_setting(
        "session_id",
        new_session
    )

    set_setting(
        "session_active",
        "1"
    )

    # =====================================================
    # CURĂȚĂM DOAR PREZENȚELE ACTIVE ALE SESIUNII NOI
    # =====================================================

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM attendance
        WHERE session_id = ?
    """, (
        new_session,
    ))

    conn.commit()
    conn.close()

    # =====================================================
    # CREĂM PANELUL
    # =====================================================

    channel = interaction.channel

    message = await channel.send(
        embed=create_panel_embed(),
        view=PresenceView()
    )

    # =====================================================
    # SALVĂM PANELUL
    # =====================================================

    set_setting(
        "panel_channel_id",
        channel.id
    )

    set_setting(
        "panel_message_id",
        message.id
    )

    print(
        f"Sesiune nouă: {new_session}"
    )

    print(
        f"Canal: {channel.id}"
    )

    print(
        f"Mesaj: {message.id}"
    )

    await interaction.followup.send(
        "🟢 Panoul de prezență a fost creat.",
        ephemeral=True
    )


# =========================================================
# /incheie_prezenta
# =========================================================

@bot.tree.command(
    name="incheie_prezenta",
    description=(
        "Încheie sesiunea de prezență."
    )
)
@app_commands.default_permissions(
    administrator=True
)
async def incheie_prezenta(
    interaction: discord.Interaction
):

    if not interaction.user.guild_permissions.administrator:

        await interaction.response.send_message(
            "❌ Nu ai permisiunea de Administrator.",
            ephemeral=True
        )

        return

    if not is_session_active():

        await interaction.response.send_message(
            "❌ Nu există o sesiune de prezență activă.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    # =====================================================
    # ÎNCHIDEM SESIUNEA
    # =====================================================

    set_setting(
        "session_active",
        "0"
    )

    # =====================================================
    # PĂSTRĂM ISTORICUL
    #
    # Dacă cineva este încă prezent, NU îi punem automat
    # ora de ieșire. Va rămâne "ÎNCĂ PREZENT" în istoric.
    # =====================================================

    try:

        channel_id = get_setting(
            "panel_channel_id",
            ""
        )

        message_id = get_setting(
            "panel_message_id",
            ""
        )

        if channel_id and message_id:

            channel = bot.get_channel(
                int(channel_id)
            )

            if channel is None:

                channel = await bot.fetch_channel(
                    int(channel_id)
                )

            panel_message = await channel.fetch_message(
                int(message_id)
            )

            await panel_message.edit(
                embed=create_panel_embed(
                    session_finished=True
                ),
                view=None
            )

    except Exception as e:

        print(
            f"Eroare la închiderea panoului: {e}"
        )

    await interaction.followup.send(
        "🔴 Prezența a fost încheiată.",
        ephemeral=True
    )


# =========================================================
# /prezenta
# =========================================================

@bot.tree.command(
    name="prezenta",
    description=(
        "Vezi dacă ești prezent "
        "în sesiunea curentă."
    )
)
async def prezenta(
    interaction: discord.Interaction
):

    if not is_session_active():

        await interaction.response.send_message(
            "❌ Nu există o sesiune activă.",
            ephemeral=True
        )

        return

    session_id = get_current_session_id()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM attendance
        WHERE session_id = ?
          AND user_id = ?
    """, (
        session_id,
        interaction.user.id
    ))

    row = cur.fetchone()

    conn.close()

    if not row:

        await interaction.response.send_message(
            "❌ Nu ești trecut ca prezent.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        (
            "🟢 **Ești prezent.**\n"
            f"🕐 Ai intrat la **{format_time(row['started_at'])}**."
        ),
        ephemeral=True
    )


# =========================================================
# /istoric_prezente
# =========================================================

@bot.tree.command(
    name="istoric_prezente",
    description=(
        "Afișează istoricul persoanelor prezente."
    )
)
@app_commands.default_permissions(
    administrator=True
)
async def istoric_prezente(
    interaction: discord.Interaction
):

    if not interaction.user.guild_permissions.administrator:

        await interaction.response.send_message(
            "❌ Nu ai permisiunea de Administrator.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    rows = get_history()

    # =====================================================
    # NU EXISTĂ ISTORIC
    # =====================================================

    if not rows:

        await interaction.followup.send(
            "📋 Nu există încă persoane în istoricul acestei sesiuni.",
            ephemeral=True
        )

        return

    # =====================================================
    # GRUPĂM DUPĂ PERSOANĂ
    # =====================================================

    grouped = group_history(
        rows
    )

    # =====================================================
    # CONSTRUIM EMBEDURI
    # =====================================================

    embeds = []

    current_embed = discord.Embed(
        title="📋 ISTORIC PREZENȚĂ",
        description=(
            f"Sesiunea #{get_current_session_id()}"
        ),
        color=discord.Color.blue()
    )

    current_embed.add_field(
        name="👥 Persoane",
        value=str(
            len(grouped)
        ),
        inline=True
    )

    current_embed.add_field(
        name="📝 Intrări",
        value=str(
            len(rows)
        ),
        inline=True
    )

    current_embed.add_field(
        name="🕐 Status",
        value="Intrări / ieșiri",
        inline=True
    )

    # =====================================================
    # ADAUGĂM PERSOANELE
    # =====================================================

    for index, person in enumerate(
        grouped,
        start=1
    ):

        name = person["display_name"]

        periods = person["periods"]

        lines = []

        for started_at, ended_at in periods:

            start_text = format_time(
                started_at
            )

            if ended_at:

                end_text = format_time(
                    ended_at
                )

                lines.append(
                    f"`{start_text} → {end_text}`"
                )

            else:

                lines.append(
                    f"`{start_text} → ÎNCĂ PREZENT`"
                )

        total_text = format_duration(
            person["total"]
        )

        value = (
            "\n".join(lines)
            + "\n"
            + f"**TOTAL: {total_text}**"
        )

        if len(value) > 1000:

            value = (
                value[:950]
                + "\n..."
            )

        # Discord permite maximum 25 fields/embed.
        # Dacă ajungem la limită, creăm alt embed.

        if len(current_embed.fields) >= 22:

            embeds.append(
                current_embed
            )

            current_embed = discord.Embed(
                title="📋 ISTORIC PREZENȚĂ — continuare",
                color=discord.Color.blue()
            )

        current_embed.add_field(
            name=f"{index}. {name}",
            value=value,
            inline=False
        )

    embeds.append(
        current_embed
    )

    # =====================================================
    # TRIMITEM EMBEDURILE
    # =====================================================

    first = True

    for embed in embeds:

        if first:

            await interaction.followup.send(
                embed=embed,
                ephemeral=True
            )

            first = False

        else:

            await interaction.followup.send(
                embed=embed,
                ephemeral=True
            )


# =========================================================
# ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):

    print(
        f"Eroare comandă Discord: {error}"
    )

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                "❌ A apărut o eroare la executarea comenzii.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "❌ A apărut o eroare la executarea comenzii.",
                ephemeral=True
            )

    except Exception as e:

        print(
            f"Nu am putut trimite mesajul de eroare: {e}"
        )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print(
        f"Bot conectat ca {bot.user}"
    )

    print(
        f"Timezone: {TIMEZONE_NAME}"
    )

    print(
        f"Database: {DB_FILE}"
    )

    bot.add_view(
        PresenceView()
    )

    try:

        synced = await bot.tree.sync()

        print(
            f"Comenzi sincronizate: {len(synced)}"
        )

    except Exception as e:

        print(
            f"Eroare la sincronizarea comenzilor: {e}"
        )


# =========================================================
# START
# =========================================================

init_db()

bot.run(TOKEN)
