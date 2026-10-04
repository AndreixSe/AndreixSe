import os
import re
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
    raise RuntimeError(
        "Lipsește DISCORD_TOKEN din variabilele de mediu."
    )


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


def format_date(iso_string):
    dt = datetime.fromisoformat(iso_string)
    return dt.astimezone(TZ).strftime("%d.%m.%Y")


def migrate_database(conn):
    cursor = conn.cursor()

    # =====================================================
    # SETTINGS
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # =====================================================
    # ATTENDANCE
    # =====================================================

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name='attendance'
    """)

    attendance_exists = cursor.fetchone()

    if attendance_exists:

        cursor.execute(
            "PRAGMA table_info(attendance)"
        )

        columns = {
            row["name"]
            for row in cursor.fetchall()
        }

        required = {
            "id",
            "session_id",
            "user_id",
            "display_name",
            "avatar_url",
            "started_at"
        }

        if not required.issubset(columns):

            print(
                "Tabelul attendance este vechi. "
                "Se reconstruiește..."
            )

            cursor.execute(
                "DROP TABLE attendance"
            )

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

    # =====================================================
    # ATTENDANCE HISTORY
    # =====================================================

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name='attendance_history'
    """)

    history_exists = cursor.fetchone()

    if history_exists:

        cursor.execute(
            "PRAGMA table_info(attendance_history)"
        )

        columns = {
            row["name"]
            for row in cursor.fetchall()
        }

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

            print(
                "Tabelul attendance_history este vechi. "
                "Se reconstruiește..."
            )

            cursor.execute(
                "DROP TABLE attendance_history"
            )

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

    # =====================================================
    # PATROLS
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patrols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            people_count INTEGER NOT NULL,
            cars_count INTEGER NOT NULL,
            color TEXT NOT NULL,
            patrol_date TEXT NOT NULL,
            patrol_time TEXT NOT NULL,
            image_url TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            created_by_id INTEGER NOT NULL,
            created_by_name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # -----------------------------------------------------
    # MIGRARE PATROLS
    # -----------------------------------------------------

    cursor.execute(
        "PRAGMA table_info(patrols)"
    )

    patrol_columns = {
        row["name"]
        for row in cursor.fetchall()
    }

    # Dacă baza veche nu avea image_url,
    # îl adăugăm fără să ștergem patrulele existente.
    if "image_url" not in patrol_columns:

        print(
            "Adaug coloana image_url în tabelul patrols..."
        )

        cursor.execute("""
            ALTER TABLE patrols
            ADD COLUMN image_url TEXT
        """)

    # =====================================================
    # PATROL PEOPLE
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patrol_people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrol_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            UNIQUE(patrol_id, user_id)
        )
    """)

    # =====================================================
    # PATROL PANEL SETTINGS
    # =====================================================

    cursor.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('patrol_channel_id', '')
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('patrol_message_id', '')
    """)

    # =====================================================
    # DEFAULT SETTINGS
    # =====================================================

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


def init_db():

    conn = get_db()

    migrate_database(conn)

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
    """, (
        key,
        str(value)
    ))

    conn.commit()

    conn.close()


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
# BOT
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# PATROL HELPERS
# =========================================================

def get_active_patrol():

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM patrols
        WHERE active = 1
        ORDER BY id DESC
        LIMIT 1
    """)

    patrol = cursor.fetchone()

    conn.close()

    return patrol


def get_patrol_people(patrol_id):

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id, display_name
        FROM patrol_people
        WHERE patrol_id = ?
        ORDER BY id ASC
    """, (
        patrol_id,
    ))

    people = cursor.fetchall()

    conn.close()

    return people


def parse_user_mentions(text):

    """
    Acceptă:

    <@123456789>
    <@!123456789>

    și extrage ID-urile Discord.
    """

    if not text:
        return []

    matches = re.findall(
        r"<@!?(\d+)>",
        text
    )

    result = []

    for match in matches:

        user_id = int(match)

        if user_id not in result:
            result.append(user_id)

    return result


# =========================================================
# CREATE PATROL EMBED
# =========================================================

def create_patrol_embed(patrol=None):

    if patrol is None:
        patrol = get_active_patrol()

    # =====================================================
    # FĂRĂ PATRULĂ
    # =====================================================

    if patrol is None:

        embed = discord.Embed(
            title="🔴 PATRULĂ",
            description=(
                "Nu există nicio patrulă activă."
            ),
            color=discord.Color.red()
        )

        embed.add_field(
            name="🚓 STATUS",
            value="**Nicio patrulă activă.**",
            inline=False
        )

        embed.set_footer(
            text="Sistem Patrule"
        )

        return embed

    # =====================================================
    # PERSOANE
    # =====================================================

    people = get_patrol_people(
        patrol["id"]
    )

    if people:

        people_text = "\n".join(
            f"👤 <@{person['user_id']}>"
            for person in people
        )

    else:

        people_text = (
            "Nicio persoană selectată."
        )

    # =====================================================
    # EMBED
    # =====================================================

    embed = discord.Embed(
        title="🚓 PATRULĂ ACTIVĂ",
        description=(
            "╔══════════════════════════════════════╗\n"
            "║          INFORMAȚII PATRULĂ          ║\n"
            "╚══════════════════════════════════════╝"
        ),
        color=discord.Color.green()
    )

    embed.add_field(
        name="📛 NUME",
        value=f"**{patrol['name']}**",
        inline=False
    )

    embed.add_field(
        name="👥 NR PERS",
        value=f"**{patrol['people_count']}**",
        inline=True
    )

    embed.add_field(
        name="🚗 NR AUTO",
        value=f"**{patrol['cars_count']}**",
        inline=True
    )

    embed.add_field(
        name="🎨 CULOARE",
        value=f"**{patrol['color']}**",
        inline=False
    )

    embed.add_field(
        name="📅 DATA",
        value=f"**{patrol['patrol_date']}**",
        inline=True
    )

    embed.add_field(
        name="🕐 ORA",
        value=f"**{patrol['patrol_time']}**",
        inline=True
    )

    embed.add_field(
        name="👮 PERSOANE",
        value=people_text,
        inline=False
    )

    # =====================================================
    # POZA
    # =====================================================

    image_url = patrol["image_url"]

    if image_url:

        embed.add_field(
            name="📸 POZA",
            value=(
                f"[🖼️ Deschide poza la rezoluție completă]"
                f"({image_url})"
            ),
            inline=False
        )

        # Imaginea apare MARE în partea de jos a embedului.
        embed.set_image(
            url=image_url
        )

    else:

        embed.add_field(
            name="📸 POZA",
            value="Nu a fost adăugată nicio poză.",
            inline=False
        )

    embed.set_footer(
        text=(
            f"Patrula #{patrol['id']} • "
            f"Pornită de {patrol['created_by_name']}"
        )
    )

    return embed


# =========================================================
# PATROL PANEL VIEW
# =========================================================

class PatrolView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="PATRULA ACTIVĂ",
        emoji="🚓",
        style=discord.ButtonStyle.success,
        custom_id="patrula_activa"
    )
    async def patrol_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        patrol = get_active_patrol()

        if patrol is None:

            await interaction.response.send_message(
                "🔴 Nu există o patrulă activă.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            embed=create_patrol_embed(patrol),
            ephemeral=True
        )


# =========================================================
# UPDATE PATROL PANEL
# =========================================================

async def update_patrol_panel():

    channel_id = get_setting(
        "patrol_channel_id"
    )

    message_id = get_setting(
        "patrol_message_id"
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

        patrol = get_active_patrol()

        if patrol:

            await message.edit(
                embed=create_patrol_embed(patrol),
                view=PatrolView()
            )

        else:

            await message.edit(
                embed=create_patrol_embed(None),
                view=None
            )

    except Exception as e:

        print(
            f"Eroare la actualizarea panoului de patrulă: {e}"
        )


# =========================================================
# PANOU PREZENȚĂ
# =========================================================

def create_panel_embed(
    session_finished=False
):

    session_id = get_current_session_id()

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id
        FROM attendance
        WHERE session_id = ?
        ORDER BY id ASC
    """, (
        session_id,
    ))

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
# UPDATE PANOU PREZENȚĂ
# =========================================================

async def update_panel():

    channel_id = get_setting(
        "panel_channel_id"
    )

    message_id = get_setting(
        "panel_message_id"
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
            embed=create_panel_embed(
                session_finished=(
                    not is_session_active()
                )
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
# BUTOANE PREZENȚĂ
# =========================================================

class PresenceView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

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

        display_name = (
            interaction.user.display_name
        )

        avatar_url = None

        if interaction.user.avatar:

            avatar_url = str(
                interaction.user.avatar.url
            )

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
# SETUP PREZENTA
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

                old_message = (
                    await old_channel.fetch_message(
                        int(old_message_id)
                    )
                )

                await old_message.delete()

        except Exception:
            pass

    old_session_id = get_current_session_id()

    new_session_id = (
        old_session_id + 1
    )

    set_setting(
        "session_id",
        new_session_id
    )

    set_setting(
        "session_active",
        "1"
    )

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
# PREZENTA
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
        (
            f"🟢 Ești prezent de la "
            f"{format_time(row['started_at'])}."
        ),
        ephemeral=True
    )


# =========================================================
# INCHEIE PREZENTA
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
    description="Arată istoricul ultimului panou."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def istoric_prezente(
    interaction: discord.Interaction
):

    session_id = get_current_session_id()

    if session_id <= 0:

        await interaction.response.send_message(
            "🔴 Nu există încă niciun panou.",
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
        ORDER BY id ASC
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
            (
                end - start
            ).total_seconds()
        )

        if seconds < 0:
            seconds = 0

        users[user_id]["intervals"].append(
            (
                format_time(
                    row["started_at"]
                ),
                format_time(
                    row["ended_at"]
                )
            )
        )

        users[user_id]["total_seconds"] += (
            seconds
        )

    embed = discord.Embed(
        title="📋 ISTORIC PREZENȚE",
        description=(
            f"**Panoul #{session_id}**\n"
            f"Prezențele înregistrate pe acest panou."
        )
    )

    for user_id, data in users.items():

        name = data["name"]

        display_name = f"@{name}"

        lines = []

        for start_time, end_time in data["intervals"]:

            lines.append(
                f"🕐 {start_time} → {end_time}"
            )

        total_seconds = (
            data["total_seconds"]
        )

        total_hours = (
            total_seconds // 3600
        )

        total_minutes = (
            total_seconds % 3600
        ) // 60

        lines.append("")

        lines.append(
            f"⏱️ **TOTAL: "
            f"{total_hours}h "
            f"{total_minutes:02d}m**"
        )

        embed.add_field(
            name=display_name,
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
# SETUP PANOU PATRULE
# =========================================================

@bot.tree.command(
    name="setup_patrule",
    description="Creează panoul pentru patrule."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def setup_patrule(
    interaction: discord.Interaction
):

    old_channel_id = get_setting(
        "patrol_channel_id"
    )

    old_message_id = get_setting(
        "patrol_message_id"
    )

    # -----------------------------------------------------
    # ȘTERGEM PANOU VECHI
    # -----------------------------------------------------

    if old_channel_id and old_message_id:

        try:

            old_channel = bot.get_channel(
                int(old_channel_id)
            )

            if old_channel:

                old_message = (
                    await old_channel.fetch_message(
                        int(old_message_id)
                    )
                )

                await old_message.delete()

        except Exception:
            pass

    # -----------------------------------------------------
    # CREĂM PANOU
    # -----------------------------------------------------

    message = await interaction.channel.send(
        embed=create_patrol_embed(None),
        view=PatrolView()
    )

    set_setting(
        "patrol_channel_id",
        interaction.channel.id
    )

    set_setting(
        "patrol_message_id",
        message.id
    )

    await interaction.response.send_message(
        "🚓 Panoul de patrule a fost creat.",
        ephemeral=True
    )


# =========================================================
# INCĂRCARE POZĂ PATRULĂ
# =========================================================

async def save_patrol_image(
    interaction: discord.Interaction,
    poza: discord.Attachment
):
    """
    Face o copie a pozei într-un mesaj Discord și
    returnează URL-ul attachment-ului copiat.

    Astfel nu mai folosim direct URL-ul primit de
    comanda slash.
    """

    if poza is None:
        return None

    allowed_types = {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/gif"
    }

    # -----------------------------------------------------
    # VERIFICĂM EXTENSIA / CONTENT TYPE
    # -----------------------------------------------------

    if (
        poza.content_type
        and poza.content_type not in allowed_types
    ):

        raise ValueError(
            "Fișierul trimis nu este o imagine. "
            "Folosește PNG, JPG, JPEG, WEBP sau GIF."
        )

    # -----------------------------------------------------
    # VERIFICĂM MĂRIMEA
    # -----------------------------------------------------

    # Discord permite diferite limite în funcție de server/
    # utilizator. Nu blocăm aici o limită artificială.
    # Discord va returna eroare dacă fișierul este prea mare.
    # -----------------------------------------------------

    # -----------------------------------------------------
    # CANAL DESTINAȚIE
    # -----------------------------------------------------

    channel = None

    patrol_channel_id = get_setting(
        "patrol_channel_id"
    )

    if patrol_channel_id:

        try:

            channel = bot.get_channel(
                int(patrol_channel_id)
            )

            if channel is None:

                channel = await bot.fetch_channel(
                    int(patrol_channel_id)
                )

        except Exception as e:

            print(
                f"Nu am putut accesa canalul de patrule: {e}"
            )

    # Dacă panoul nu există încă, folosim canalul
    # în care a fost executată comanda.
    if channel is None:

        channel = interaction.channel

    if channel is None:

        raise ValueError(
            "Nu am găsit un canal în care să salvez poza."
        )

    # -----------------------------------------------------
    # DESCĂRCĂM FIȘIERUL
    # -----------------------------------------------------

    file_data = await poza.to_file()

    # -----------------------------------------------------
    # TRIMITEM COPIA PE DISCORD
    # -----------------------------------------------------

    photo_message = await channel.send(
        content=(
            f"📸 **Poză patrulă** • "
            f"Încărcată de {interaction.user.mention}"
        ),
        file=file_data
    )

    # -----------------------------------------------------
    # LUĂM URL-UL COPIEI
    # -----------------------------------------------------

    if not photo_message.attachments:

        raise ValueError(
            "Poza a fost trimisă, dar Discord nu a returnat attachment-ul."
        )

    saved_attachment = (
        photo_message.attachments[0]
    )

    saved_url = saved_attachment.url

    print(
        f"Poză patrulă salvată: {saved_url}"
    )

    return saved_url


# =========================================================
# INCEPE PATRULA
# =========================================================

@bot.tree.command(
    name="incepe_patrula",
    description="Pornește o patrulă nouă."
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.describe(
    nume="Numele patrulei",
    persoane="Menționează persoanele: @Persoana1 @Persoana2",
    nr_auto="Numărul de mașini",
    culoare="Culoarea mașinilor",
    data="Data patrulei, ex: 04.10.2026",
    ora="Ora patrulei, ex: 21:30",
    poza="Poza patrulei"
)
async def incepe_patrula(
    interaction: discord.Interaction,
    nume: str,
    persoane: str,
    nr_auto: int,
    culoare: str,
    data: str = None,
    ora: str = None,
    poza: discord.Attachment = None
):

    # =====================================================
    # VERIFICĂM DACĂ EXISTĂ DEJA O PATRULĂ
    # =====================================================

    existing = get_active_patrol()

    if existing:

        await interaction.response.send_message(
            (
                "🔴 Există deja o patrulă activă:\n"
                f"🚓 **{existing['name']}**\n"
                f"👥 Persoane: {existing['people_count']}\n"
                f"🚗 Auto: {existing['cars_count']}"
            ),
            ephemeral=True
        )

        return

    # =====================================================
    # VALIDARE AUTO
    # =====================================================

    if nr_auto < 1:

        await interaction.response.send_message(
            "🔴 Numărul de mașini trebuie să fie cel puțin 1.",
            ephemeral=True
        )

        return

    # =====================================================
    # PARSĂM PERSOANELE
    # =====================================================

    user_ids = parse_user_mentions(
        persoane
    )

    if not user_ids:

        await interaction.response.send_message(
            (
                "🔴 Nu am găsit nicio persoană.\n\n"
                "Folosește mențiuni Discord, de exemplu:\n"
                "`@Dominicans @Ion @Alex`"
            ),
            ephemeral=True
        )

        return

    # =====================================================
    # DATA / ORA
    # =====================================================

    current = now_local()

    if not data:

        patrol_date = current.strftime(
            "%d.%m.%Y"
        )

    else:

        patrol_date = data

    if not ora:

        patrol_time = current.strftime(
            "%H:%M"
        )

    else:

        patrol_time = ora

    # =====================================================
    # RĂSPUNDEM DEFERRED
    # =====================================================
    # Facem defer pentru că încărcarea/copierea pozei
    # poate dura câteva secunde.

    await interaction.response.defer(
        ephemeral=True
    )

    # =====================================================
    # POZA
    # =====================================================

    image_url = None

    if poza:

        try:

            image_url = await save_patrol_image(
                interaction,
                poza
            )

        except ValueError as e:

            await interaction.followup.send(
                f"🔴 {e}",
                ephemeral=True
            )

            return

        except discord.HTTPException as e:

            print(
                f"Eroare Discord la încărcarea pozei: {e}"
            )

            await interaction.followup.send(
                (
                    "🔴 Nu am putut salva poza pe Discord.\n"
                    "Verifică dimensiunea fișierului și "
                    "permisiunile botului în canal."
                ),
                ephemeral=True
            )

            return

        except Exception as e:

            print(
                f"Eroare la salvarea pozei: {e}"
            )

            await interaction.followup.send(
                (
                    "🔴 A apărut o eroare la salvarea pozei."
                ),
                ephemeral=True
            )

            return

    # =====================================================
    # CREĂM PATRULA
    # =====================================================

    conn = get_db()

    cursor = conn.cursor()

    started_at = now_iso()

    cursor.execute("""
        INSERT INTO patrols (
            name,
            people_count,
            cars_count,
            color,
            patrol_date,
            patrol_time,
            image_url,
            started_at,
            ended_at,
            created_by_id,
            created_by_name,
            active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 1)
    """, (
        nume,
        len(user_ids),
        nr_auto,
        culoare,
        patrol_date,
        patrol_time,
        image_url,
        started_at,
        interaction.user.id,
        interaction.user.display_name
    ))

    patrol_id = cursor.lastrowid

    # =====================================================
    # SALVĂM PERSOANELE
    # =====================================================

    for user_id in user_ids:

        member = interaction.guild.get_member(
            user_id
        )

        if member:

            display_name = (
                member.display_name
            )

        else:

            try:

                user = await bot.fetch_user(
                    user_id
                )

                display_name = (
                    user.display_name
                )

            except Exception:

                display_name = str(
                    user_id
                )

        cursor.execute("""
            INSERT OR IGNORE INTO patrol_people (
                patrol_id,
                user_id,
                display_name
            )
            VALUES (?, ?, ?)
        """, (
            patrol_id,
            user_id,
            display_name
        ))

    conn.commit()

    conn.close()

    # =====================================================
    # ACTUALIZĂM PANOU
    # =====================================================

    await update_patrol_panel()

    # =====================================================
    # RĂSPUNS
    # =====================================================

    photo_status = (
        "📸 Poza a fost salvată și afișată în panou."
        if image_url
        else
        "📸 Nu a fost adăugată nicio poză."
    )

    await interaction.followup.send(
        (
            "🟢 **Patrula a fost pornită cu succes!**\n\n"
            f"🚓 **{nume}**\n"
            f"👥 Persoane: **{len(user_ids)}**\n"
            f"🚗 Mașini: **{nr_auto}**\n"
            f"🎨 Culoare: **{culoare}**\n"
            f"📅 Data: **{patrol_date}**\n"
            f"🕐 Ora: **{patrol_time}**\n"
            f"{photo_status}"
        ),
        ephemeral=True
    )


# =========================================================
# INCHEIE PATRULA
# =========================================================

@bot.tree.command(
    name="incheie_patrula",
    description="Încheie patrula activă."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def incheie_patrula(
    interaction: discord.Interaction
):

    patrol = get_active_patrol()

    if patrol is None:

        await interaction.response.send_message(
            "🔴 Nu există nicio patrulă activă.",
            ephemeral=True
        )

        return

    ended_at = now_iso()

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE patrols
        SET active = 0,
            ended_at = ?
        WHERE id = ?
    """, (
        ended_at,
        patrol["id"]
    ))

    conn.commit()

    conn.close()

    await update_patrol_panel()

    await interaction.response.send_message(
        (
            "🔴 **Patrula a fost încheiată.**\n\n"
            f"🚓 Nume: **{patrol['name']}**\n"
            f"👥 Persoane: **{patrol['people_count']}**\n"
            f"🚗 Mașini: **{patrol['cars_count']}**\n"
            f"🕐 Încheiată la: **{format_time(ended_at)}**"
        ),
        ephemeral=True
    )


# =========================================================
# PATRULA
# =========================================================

@bot.tree.command(
    name="patrula",
    description="Afișează patrula activă."
)
async def patrula(
    interaction: discord.Interaction
):

    active_patrol = get_active_patrol()

    if active_patrol is None:

        await interaction.response.send_message(
            "🔴 Nu există nicio patrulă activă.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        embed=create_patrol_embed(
            active_patrol
        ),
        ephemeral=True
    )


# =========================================================
# ISTORIC PATRULE
# =========================================================

@bot.tree.command(
    name="istoric_patrule",
    description="Afișează ultimele patrule."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def istoric_patrule(
    interaction: discord.Interaction
):

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            people_count,
            cars_count,
            color,
            patrol_date,
            patrol_time,
            image_url,
            started_at,
            ended_at,
            created_by_name,
            active
        FROM patrols
        ORDER BY id DESC
        LIMIT 10
    """)

    rows = cursor.fetchall()

    conn.close()

    if not rows:

        await interaction.response.send_message(
            "📋 Nu există patrule înregistrate.",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="📋 ISTORIC PATRULE",
        description="Ultimele 10 patrule înregistrate."
    )

    for row in rows:

        status = (
            "🟢 ACTIVĂ"
            if row["active"]
            else "🔴 ÎNCHEIATĂ"
        )

        value = (
            f"**{status}**\n"
            f"👥 Persoane: **{row['people_count']}**\n"
            f"🚗 Auto: **{row['cars_count']}**\n"
            f"🎨 Culoare: **{row['color']}**\n"
            f"📅 {row['patrol_date']} • 🕐 {row['patrol_time']}\n"
            f"👮 Pornită de: **{row['created_by_name']}**"
        )

        if row["image_url"]:

            value += (
                "\n📸 "
                f"[Vezi poza]({row['image_url']})"
            )

        embed.add_field(
            name=f"🚓 #{row['id']} • {row['name']}",
            value=value,
            inline=False
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

        message = (
            "🔴 A apărut o eroare la executarea comenzii."
        )

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

# Panouri persistente
bot.add_view(
    PresenceView()
)

bot.add_view(
    PatrolView()
)

bot.run(TOKEN)