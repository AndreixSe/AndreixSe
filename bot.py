import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Bucharest")

TZ = ZoneInfo(TIMEZONE)

if not TOKEN:
    raise RuntimeError("Lipsește DISCORD_TOKEN din variabilele de mediu.")


if os.path.isdir("/data"):
    DB_PATH = "/data/pontaj.db"
else:
    DB_PATH = "pontaj.db"


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_local():
    return datetime.now(TZ)


def now_iso():
    return now_local().isoformat()


def format_time(iso_string):
    dt = datetime.fromisoformat(iso_string)
    return dt.astimezone(TZ).strftime("%H:%M")


def migrate_database(conn):
    cursor = conn.cursor()

    # -----------------------------------------------------
    # SETTINGS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # -----------------------------------------------------
    # ATTENDANCE
    # -----------------------------------------------------

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name='attendance'
    """)

    attendance_exists = cursor.fetchone()

    if attendance_exists:
        cursor.execute("PRAGMA table_info(attendance)")
        columns = {row["name"] for row in cursor.fetchall()}

        required = {
            "id",
            "session_id",
            "user_id",
            "display_name",
            "avatar_url",
            "started_at"
        }

        if not required.issubset(columns):
            print("Tabelul attendance este vechi. Se reconstruiește...")
            cursor.execute("DROP TABLE attendance")

    cursor.execute("""
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

    # -----------------------------------------------------
    # ATTENDANCE HISTORY
    # -----------------------------------------------------

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name='attendance_history'
    """)

    history_exists = cursor.fetchone()

    if history_exists:
        cursor.execute("PRAGMA table_info(attendance_history)")
        columns = {row["name"] for row in cursor.fetchall()}

        required = {
            "id",
            "session_id",
            "user_id",
            "display_name",
            "avatar_url",
            "started_at",
            "ended_at"
        }

        if not required.issubset(columns):
            print("Tabelul attendance_history este vechi. Se reconstruiește...")
            cursor.execute("DROP TABLE attendance_history")

    cursor.execute("""
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

    conn.commit()


def init_db():
    conn = get_db()

    migrate_database(conn)

    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('session_id', '0')
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('session_active', '0')
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('panel_channel_id', '')
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('panel_message_id', '')
    """)

    conn.commit()
    conn.close()

    print("Database inițializată cu succes.")


# =========================================================
# SETTINGS
# =========================================================

def get_setting(key, default=None):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    )

    row = cursor.fetchone()

    conn.close()

    if row is None:
        return default

    return row["value"]


def set_setting(key, value):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
    """, (key, str(value)))

    conn.commit()
    conn.close()


def get_current_session_id():
    return int(get_setting("session_id", "0"))


def is_session_active():
    return get_setting("session_active", "0") == "1"


# =========================================================
# BOT
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# PANEL EMBED
# =========================================================

def create_panel_embed(session_finished=False):
    session_id = get_current_session_id()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id
        FROM attendance
        WHERE session_id = ?
        ORDER BY id ASC
    """, (session_id,))

    users = cursor.fetchall()

    conn.close()

    if session_finished:
        title = "🔴 PREZENȚĂ"
    else:
        title = "🟢 PREZENȚĂ"

    embed = discord.Embed(
        title=title
    )

    if users:
        lines = []

        for user in users:
            lines.append(
                f"🟢 <@{user['user_id']}>"
            )

        value = "\n".join(lines)

    else:
        value = "Nimeni nu este prezent."

    embed.add_field(
        name="👥 Persoane prezente",
        value=value,
        inline=False
    )

    embed.set_footer(
        text="Lista se actualizează automat."
    )

    return embed


# =========================================================
# UPDATE PANEL
# =========================================================

async def update_panel():
    channel_id = get_setting("panel_channel_id")
    message_id = get_setting("panel_message_id")

    if not channel_id or not message_id:
        return

    try:
        channel = bot.get_channel(int(channel_id))

        if channel is None:
            channel = await bot.fetch_channel(
                int(channel_id)
            )

        message = await channel.fetch_message(
            int(message_id)
        )

        await message.edit(
            embed=create_panel_embed(
                session_finished=not is_session_active()
            ),
            view=(
                PresenceView()
                if is_session_active()
                else None
            )
        )

    except Exception as e:
        print(
            f"Eroare la actualizarea panoului: {e}"
        )


# =========================================================
# PRESENCE VIEW
# =========================================================

class PresenceView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    # -----------------------------------------------------
    # PREZENT
    # -----------------------------------------------------

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

        session_id = get_current_session_id()
        user_id = interaction.user.id

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id
            FROM attendance
            WHERE session_id = ?
            AND user_id = ?
        """, (
            session_id,
            user_id
        ))

        existing = cursor.fetchone()

        if existing:
            conn.close()

            await interaction.response.defer(
                ephemeral=True
            )

            return

        current_time = now_iso()

        display_name = interaction.user.display_name

        avatar_url = None

        if interaction.user.avatar:
            avatar_url = str(
                interaction.user.avatar.url
            )

        # Adăugăm pe panoul activ.
        cursor.execute("""
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
            user_id,
            display_name,
            avatar_url,
            current_time
        ))

        # Salvăm intervalul în istoric.
        cursor.execute("""
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
            user_id,
            display_name,
            avatar_url,
            current_time
        ))

        conn.commit()
        conn.close()

        await interaction.response.defer(
            ephemeral=True
        )

        await update_panel()

    # -----------------------------------------------------
    # NEPREZENT
    # -----------------------------------------------------

    @discord.ui.button(
        label="NEPREZENT",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        custom_id="pontaj_plecare"
    )
    async def neprezent(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not is_session_active():
            await interaction.response.defer(
                ephemeral=True
            )
            return

        session_id = get_current_session_id()
        user_id = interaction.user.id

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id
            FROM attendance
            WHERE session_id = ?
            AND user_id = ?
        """, (
            session_id,
            user_id
        ))

        active = cursor.fetchone()

        if not active:
            conn.close()

            await interaction.response.defer(
                ephemeral=True
            )

            return

        current_time = now_iso()

        # Căutăm ultimul interval deschis.
        cursor.execute("""
            SELECT id
            FROM attendance_history
            WHERE session_id = ?
            AND user_id = ?
            AND ended_at IS NULL
            ORDER BY id DESC
            LIMIT 1
        """, (
            session_id,
            user_id
        ))

        history_row = cursor.fetchone()

        if history_row:
            cursor.execute("""
                UPDATE attendance_history
                SET ended_at = ?
                WHERE id = ?
            """, (
                current_time,
                history_row["id"]
            ))

        # Scoatem persoana de pe panou.
        cursor.execute("""
            DELETE FROM attendance
            WHERE session_id = ?
            AND user_id = ?
        """, (
            session_id,
            user_id
        ))

        conn.commit()
        conn.close()

        await interaction.response.defer(
            ephemeral=True
        )

        await update_panel()


# =========================================================
# SETUP PREZENȚĂ
# =========================================================

@bot.tree.command(
    name="setup_prezenta",
    description="Creează un nou panou de prezență."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def setup_prezenta(
    interaction: discord.Interaction
):
    # Ștergem panoul vechi dacă există.
    old_channel_id = get_setting(
        "panel_channel_id"
    )

    old_message_id = get_setting(
        "panel_message_id"
    )

    if old_channel_id and old_message_id:

        try:
            old_channel = bot.get_channel(
                int(old_channel_id)
            )

            if old_channel:

                old_message = await old_channel.fetch_message(
                    int(old_message_id)
                )

                await old_message.delete()

        except Exception:
            pass

    # Creăm un nou session_id.
    old_session_id = get_current_session_id()

    new_session_id = old_session_id + 1

    set_setting(
        "session_id",
        new_session_id
    )

    set_setting(
        "session_active",
        "1"
    )

    # Noul panou începe gol.
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM attendance
        WHERE session_id = ?
    """, (
        new_session_id,
    ))

    conn.commit()
    conn.close()

    # Trimitem panoul.
    message = await interaction.channel.send(
        embed=create_panel_embed(),
        view=PresenceView()
    )

    set_setting(
        "panel_channel_id",
        interaction.channel.id
    )

    set_setting(
        "panel_message_id",
        message.id
    )

    await interaction.response.send_message(
        "🟢 Panoul de prezență a fost creat.",
        ephemeral=True
    )


# =========================================================
# PREZENȚA MEA
# =========================================================

@bot.tree.command(
    name="prezenta",
    description="Verifică dacă ești prezent."
)
async def prezenta(
    interaction: discord.Interaction
):
    if not is_session_active():

        await interaction.response.send_message(
            "🔴 Nu există un panou de prezență activ.",
            ephemeral=True
        )

        return

    session_id = get_current_session_id()
    user_id = interaction.user.id

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT started_at
        FROM attendance
        WHERE session_id = ?
        AND user_id = ?
    """, (
        session_id,
        user_id
    ))

    row = cursor.fetchone()

    conn.close()

    if not row:

        await interaction.response.send_message(
            "🔴 Nu ești prezent.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        f"🟢 Ești prezent de la {format_time(row['started_at'])}.",
        ephemeral=True
    )


# =========================================================
# ÎNCHEIE PREZENȚA
# =========================================================

@bot.tree.command(
    name="incheie_prezenta",
    description="Închide panoul actual de prezență."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def incheie_prezenta(
    interaction: discord.Interaction
):
    if not is_session_active():

        await interaction.response.send_message(
            "🔴 Nu există un panou activ.",
            ephemeral=True
        )

        return

    set_setting(
        "session_active",
        "0"
    )

    await update_panel()

    await interaction.response.send_message(
        "🔴 Panoul de prezență a fost închis.",
        ephemeral=True
    )


# =========================================================
# ISTORIC PREZENTE
# =========================================================

@bot.tree.command(
    name="istoric_prezente",
    description="Arată prezențele de pe ultimul panou."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def istoric_prezente(
    interaction: discord.Interaction
):
    # =====================================================
    # IMPORTANT:
    # Luăm DOAR ultimul panou.
    # Nu folosim data.
    # Nu folosim panourile vechi.
    # =====================================================

    session_id = get_current_session_id()

    if session_id <= 0:

        await interaction.response.send_message(
            "🔴 Nu există încă niciun panou de prezență.",
            ephemeral=True
        )

        return

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            user_id,
            display_name,
            started_at,
            ended_at
        FROM attendance_history
        WHERE session_id = ?
        AND ended_at IS NOT NULL
        ORDER BY display_name ASC, started_at ASC
    """, (
        session_id,
    ))

    rows = cursor.fetchall()

    conn.close()

    if not rows:

        await interaction.response.send_message(
            "📋 Nu există prezențe înregistrate pe acest panou.",
            ephemeral=True
        )

        return

    # =====================================================
    # GRUPARE PERSOANE
    # =====================================================

    users = {}

    for row in rows:

        user_id = row["user_id"]

        if user_id not in users:

            users[user_id] = {
                "name": row["display_name"],
                "intervals": [],
                "total_seconds": 0
            }

        start = datetime.fromisoformat(
            row["started_at"]
        )

        end = datetime.fromisoformat(
            row["ended_at"]
        )

        seconds = int(
            (end - start).total_seconds()
        )

        if seconds < 0:
            seconds = 0

        users[user_id]["intervals"].append(
            (
                format_time(row["started_at"]),
                format_time(row["ended_at"])
            )
        )

        users[user_id]["total_seconds"] += seconds

    # =====================================================
    # EMBED MARE
    # =====================================================

    embed = discord.Embed(
        title="📋 ISTORIC PREZENȚE",
        description=(
            f"**Prezențele de pe panoul actual**\n\n"
            f"Panou #{session_id}"
        )
    )

    # Facem embed-ul mai mare vizual.
    embed.set_thumbnail(
        url=bot.user.display_avatar.url
    )

    for user_id, data in users.items():

        lines = []

        # Intervalele.
        for start_time, end_time in data["intervals"]:

            lines.append(
                f"🕐 **{start_time} → {end_time}**"
            )

        # Total.
        total_seconds = data["total_seconds"]

        total_hours = total_seconds // 3600

        total_minutes = (
            total_seconds % 3600
        ) // 60

        lines.append("")

        lines.append(
            f"⏱️ **TOTAL: {total_hours}h {total_minutes:02d}m**"
        )

        # =================================================
        # IMPORTANT:
        # Nu mai folosim <@ID>.
        # Folosim numele salvat.
        # Astfel apare:
        #
        # @Andrei
        #
        # și nu:
        #
        # <@123456789>
        # =================================================

        person_name = data["name"]

        field_name = f"@{person_name}"

        embed.add_field(
            name=field_name,
            value="\n".join(lines),
            inline=False
        )

    embed.set_footer(
        text="Istoric • ultimul panou de prezență"
    )

    await interaction.response.send_message(
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
    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):
        message = (
            "🔴 Nu ai permisiunea necesară "
            "pentru această comandă."
        )

    else:

        print(
            f"Eroare comandă: {error}"
        )

        message = "🔴 A apărut o eroare."

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                message,
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                message,
                ephemeral=True
            )

    except Exception:
        pass


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print(
        f"Bot conectat ca {bot.user}"
    )

    print(
        f"Timezone: {TIMEZONE}"
    )

    print(
        f"Database: {DB_PATH}"
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

bot.add_view(
    PresenceView()
)

bot.run(TOKEN)