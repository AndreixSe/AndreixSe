````python
import os
import sqlite3
from datetime import datetime
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
# DATABASE FUNCTIONS
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = get_db()
    cur = conn.cursor()

    # =====================================================
    # TABEL PREZENȚĂ
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
    # SETĂRI
    # =====================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('session_id', '0')
    """)

    cur.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('session_active', '0')
    """)

    cur.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('panel_channel_id', '')
    """)

    cur.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('panel_message_id', '')
    """)

    conn.commit()
    conn.close()


def get_setting(key, default=None):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    )

    row = cur.fetchone()

    conn.close()

    if row is None:
        return default

    return row["value"]


def set_setting(key, value):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
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
# TIME
# =========================================================

def now_local():

    return datetime.now(TZ)


def format_time(value):

    try:

        dt = datetime.fromisoformat(value)

        return dt.astimezone(TZ).strftime(
            "%H:%M"
        )

    except Exception:

        return "--:--"


# =========================================================
# PANEL EMBED
# =========================================================

def create_panel_embed(
    session_finished=False
):

    # =====================================================
    # HEADER
    # =====================================================

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

    # =====================================================
    # PERSOANE PREZENTE
    # =====================================================

    users = get_present_users()

    if not users:

        embed.add_field(
            name="👥 Persoane prezente",
            value="Nimeni nu este prezent.",
            inline=False
        )

    else:

        # Header tabel
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

            # Limităm numele pentru a nu rupe tabelul
            if len(name) > 24:
                name = name[:21] + "..."

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

    # =====================================================
    # AVATARURI
    # =====================================================

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

    # =====================================================
    # FOOTER
    # =====================================================

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
# VIEW
# =========================================================

class PresenceView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    # =====================================================
    # BUTON PREZENT
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

        # -------------------------------------------------
        # Verificăm sesiunea
        # -------------------------------------------------

        if not is_session_active():

            await interaction.response.send_message(
                "❌ Momentan nu există o sesiune "
                "de prezență activă.",
                ephemeral=True
            )

            return

        user = interaction.user

        session_id = (
            get_current_session_id()
        )

        # -------------------------------------------------
        # Avatar
        # -------------------------------------------------

        avatar_url = None

        if user.display_avatar:

            avatar_url = str(
                user.display_avatar.url
            )

        # -------------------------------------------------
        # Database
        # -------------------------------------------------

        conn = get_db()
        cur = conn.cursor()

        # -------------------------------------------------
        # Verificăm dacă este deja prezent
        # -------------------------------------------------

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

            await interaction.response.send_message(
                "🟢 Ești deja în lista persoanelor prezente.",
                ephemeral=True
            )

            return

        # -------------------------------------------------
        # Adăugăm persoana
        # -------------------------------------------------

        current_time = now_local().isoformat()

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

        conn.commit()
        conn.close()

        # -------------------------------------------------
        # Răspuns
        # -------------------------------------------------

        await interaction.response.send_message(
            "🟢 Ai fost adăugat în lista de prezență.",
            ephemeral=True
        )

        # -------------------------------------------------
        # Actualizăm panoul
        # -------------------------------------------------

        await update_panel()

    # =====================================================
    # BUTON PLECARE
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

        # -------------------------------------------------
        # Verificăm sesiunea
        # -------------------------------------------------

        if not is_session_active():

            await interaction.response.send_message(
                "❌ Momentan nu există o sesiune "
                "de prezență activă.",
                ephemeral=True
            )

            return

        user = interaction.user

        session_id = (
            get_current_session_id()
        )

        # -------------------------------------------------
        # Database
        # -------------------------------------------------

        conn = get_db()
        cur = conn.cursor()

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

        if not existing:

            conn.close()

            await interaction.response.send_message(
                "❌ Nu ești în lista persoanelor prezente.",
                ephemeral=True
            )

            return

        # -------------------------------------------------
        # Ștergem persoana din lista curentă
        # -------------------------------------------------

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

        # -------------------------------------------------
        # Răspuns
        # -------------------------------------------------

        await interaction.response.send_message(
            "🔴 Ai fost scos din lista de prezență.",
            ephemeral=True
        )

        # -------------------------------------------------
        # Actualizăm panoul
        # -------------------------------------------------

        await update_panel()


# =========================================================
# ACTUALIZARE PANEL
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

        # -------------------------------------------------
        # Canal
        # -------------------------------------------------

        channel = bot.get_channel(
            int(channel_id)
        )

        if channel is None:

            channel = await bot.fetch_channel(
                int(channel_id)
            )

        # -------------------------------------------------
        # Mesaj
        # -------------------------------------------------

        message = await channel.fetch_message(
            int(message_id)
        )

        # -------------------------------------------------
        # Actualizare
        # -------------------------------------------------

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
# SETUP PREZENȚĂ
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

    # =====================================================
    # ADMIN
    # =====================================================

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
    # ȘTERGEM VECHIUL PANEL
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
    # CURĂȚĂM SESIUNEA NOUĂ
    # =====================================================

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM attendance WHERE session_id = ?",
        (new_session,)
    )

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

    # =====================================================
    # CONFIRMARE
    # =====================================================

    await interaction.followup.send(
        "🟢 Panoul de prezență a fost creat.",
        ephemeral=True
    )


# =========================================================
# ÎNCHEIE PREZENȚA
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

    # =====================================================
    # ADMIN
    # =====================================================

    if not interaction.user.guild_permissions.administrator:

        await interaction.response.send_message(
            "❌ Nu ai permisiunea de Administrator.",
            ephemeral=True
        )

        return

    # =====================================================
    # VERIFICĂM SESIUNEA
    # =====================================================

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
    # OPRIM SESIUNEA
    # =====================================================

    set_setting(
        "session_active",
        "0"
    )

    # =====================================================
    # ACTUALIZĂM PANELUL
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

    # =====================================================
    # CONFIRMARE
    # =====================================================

    await interaction.followup.send(
        "🔴 Prezența a fost încheiată.",
        ephemeral=True
    )


# =========================================================
# PREZENȚA MEA
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

    # =====================================================
    # VERIFICĂM SESIUNEA
    # =====================================================

    if not is_session_active():

        await interaction.response.send_message(
            "❌ Nu există o sesiune activă.",
            ephemeral=True
        )

        return

    session_id = (
        get_current_session_id()
    )

    # =====================================================
    # DATABASE
    # =====================================================

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

    # =====================================================
    # NU ESTE PREZENT
    # =====================================================

    if not row:

        await interaction.response.send_message(
            "❌ Nu ești trecut ca prezent.",
            ephemeral=True
        )

        return

    # =====================================================
    # ESTE PREZENT
    # =====================================================

    await interaction.response.send_message(
        (
            "🟢 **Ești prezent.**\n"
            f"🕐 Ai intrat la **{format_time(row['started_at'])}**."
        ),
        ephemeral=True
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

    # =====================================================
    # VIEW PERSISTENT
    # =====================================================

    bot.add_view(
        PresenceView()
    )

    # =====================================================
    # SLASH COMMANDS
    # =====================================================

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
````
