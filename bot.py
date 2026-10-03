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

# Railway Volume
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
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

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
    """, (key, str(value)))

    conn.commit()
    conn.close()


def get_current_session_id():
    return int(get_setting("session_id", "0"))


def is_session_active():
    return get_setting("session_active", "0") == "1"


def get_present_users():
    session_id = get_current_session_id()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM attendance
        WHERE session_id = ?
        ORDER BY started_at ASC
    """, (session_id,))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================================================
# TIMP
# =========================================================

def now_local():
    return datetime.now(TZ)


def format_datetime(value):
    try:
        dt = datetime.fromisoformat(value)
        return dt.astimezone(TZ).strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return value


def format_duration(started_at):
    try:
        start = datetime.fromisoformat(started_at)
        end = now_local()

        seconds = int((end - start).total_seconds())

        if seconds < 0:
            seconds = 0

        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        return f"{hours}h {minutes}m {secs}s"

    except Exception:
        return "-"


# =========================================================
# PANEL
# =========================================================

def create_panel_embed():
    embed = discord.Embed(
        title="🟢 PREZENȚĂ",
        description=(
            "Apasă butonul **🟢 PREZENT** pentru a fi trecut "
            "direct pe lista de prezenți.\n\n"
            "### 👥 Persoane prezente"
        ),
        color=discord.Color.green()
    )

    users = get_present_users()

    if not users:
        embed.add_field(
            name="Nimeni nu este prezent",
            value="Apasă **🟢 PREZENT** pentru a te trece pe listă.",
            inline=False
        )
    else:
        lines = []

        for index, user in enumerate(users, start=1):
            name = user["display_name"]

            lines.append(
                f"**{index}. {name}**\n"
                f"🕐 {format_datetime(user['started_at'])}"
            )

        embed.add_field(
            name=f"👥 Prezenți: {len(users)}",
            value="\n\n".join(lines),
            inline=False
        )

    embed.set_footer(
        text="Lista se actualizează automat când cineva apasă PREZENT."
    )

    return embed


# =========================================================
# PANEL CU AVATARURI
# =========================================================

async def update_panel():
    channel_id = get_setting("panel_channel_id", "")
    message_id = get_setting("panel_message_id", "")

    if not channel_id or not message_id:
        return

    try:
        channel = bot.get_channel(int(channel_id))

        if channel is None:
            channel = await bot.fetch_channel(int(channel_id))

        message = await channel.fetch_message(int(message_id))

        # Embed principal
        embeds = [create_panel_embed()]

        # Un embed pentru fiecare persoană,
        # astfel încât fiecare avatar să apară direct în panou.
        users = get_present_users()

        for user in users:
            avatar_url = user["avatar_url"]

            person_embed = discord.Embed(
                description=(
                    f"**{user['display_name']}**\n"
                    f"🕐 Prezent de la "
                    f"`{format_datetime(user['started_at'])}`\n"
                    f"⏱️ Durată: `{format_duration(user['started_at'])}`"
                ),
                color=discord.Color.green()
            )

            if avatar_url:
                person_embed.set_thumbnail(url=avatar_url)

            embeds.append(person_embed)

        # Discord permite maximum 10 embed-uri într-un mesaj.
        # Dacă sunt mai mult de 9 persoane, păstrăm lista principală
        # și avatarurile primelor 9.
        embeds = embeds[:10]

        await message.edit(
            content=None,
            embeds=embeds,
            view=PresenceView()
        )

    except discord.NotFound:
        print("Panoul nu mai există în Discord.")

    except Exception as e:
        print(f"Eroare la actualizarea panoului: {e}")


# =========================================================
# BUTON PREZENT
# =========================================================

class PresenceView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

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

        # Nu există sesiune activă
        if not is_session_active():

            # Răspuns invizibil / ephemeral.
            # Nu apare mesaj public în canal.
            await interaction.response.send_message(
                "Momentan nu există o sesiune de prezență activă.",
                ephemeral=True
            )
            return

        user = interaction.user
        session_id = get_current_session_id()

        avatar_url = None

        if user.display_avatar:
            avatar_url = user.display_avatar.url

        conn = get_db()
        cur = conn.cursor()

        # Verificăm dacă persoana este deja prezentă
        cur.execute("""
            SELECT id
            FROM attendance
            WHERE session_id = ?
              AND user_id = ?
        """, (session_id, user.id))

        existing = cur.fetchone()

        if existing:
            conn.close()

            # Nu afișăm nimic public.
            await interaction.response.defer(ephemeral=True)
            return

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

        # Răspuns invizibil pentru Discord.
        await interaction.response.defer(ephemeral=True)

        # Actualizăm direct panoul
        await update_panel()


# =========================================================
# SETUP PREZENȚĂ
# =========================================================

@bot.tree.command(
    name="setup_prezenta",
    description="Creează panoul de prezență și pornește o sesiune nouă."
)
@app_commands.default_permissions(administrator=True)
async def setup_prezenta(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "Nu ai permisiunea de Administrator.",
            ephemeral=True
        )
        return

    # Răspuns invizibil
    await interaction.response.defer(ephemeral=True)

    # Pornim o sesiune nouă
    old_session = get_current_session_id()
    new_session = old_session + 1

    set_setting("session_id", new_session)
    set_setting("session_active", "1")

    # Ștergem eventualele date rămase din sesiunea nouă
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM attendance WHERE session_id = ?",
        (new_session,)
    )

    conn.commit()
    conn.close()

    # Canalul unde se execută comanda
    channel = interaction.channel

    # Creăm panoul
    embed = create_panel_embed()

    message = await channel.send(
        embeds=[embed],
        view=PresenceView()
    )

    set_setting("panel_channel_id", channel.id)
    set_setting("panel_message_id", message.id)

    print(
        f"Sesiune nouă de prezență: {new_session} "
        f"| Canal: {channel.id} "
        f"| Mesaj: {message.id}"
    )


# =========================================================
# ÎNCHEIE PREZENȚA
# =========================================================

@bot.tree.command(
    name="incheie_prezenta",
    description="Încheie sesiunea de prezență și generează raportul."
)
@app_commands.default_permissions(administrator=True)
async def incheie_prezenta(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "Nu ai permisiunea de Administrator.",
            ephemeral=True
        )
        return

    if not is_session_active():
        await interaction.response.send_message(
            "Nu există o sesiune de prezență activă.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    users = get_present_users()

    # Oprim sesiunea
    set_setting("session_active", "0")

    # =====================================================
    # RAPORT
    # =====================================================

    report_embed = discord.Embed(
        title="📋 RAPORT PREZENȚĂ",
        description=(
            f"Sesiunea **#{get_current_session_id()}** "
            f"a fost încheiată."
        ),
        color=discord.Color.blue(),
        timestamp=now_local()
    )

    if not users:
        report_embed.add_field(
            name="👥 Prezenți",
            value="Nicio persoană nu a fost prezentă.",
            inline=False
        )

    else:
        report_embed.add_field(
            name="👥 Total persoane prezente",
            value=f"**{len(users)}**",
            inline=False
        )

    report_embed.set_footer(
        text="Raport generat de bot."
    )

    # Trimitem raportul în canalul în care a fost dată comanda
    await interaction.channel.send(
        embed=report_embed
    )

    # Un embed separat pentru fiecare persoană
    for user in users:

        person_embed = discord.Embed(
            title=f"👤 {user['display_name']}",
            color=discord.Color.green()
        )

        person_embed.add_field(
            name="🟢 Prezent de la",
            value=format_datetime(user["started_at"]),
            inline=False
        )

        person_embed.add_field(
            name="⏱️ Durată",
            value=format_duration(user["started_at"]),
            inline=False
        )

        if user["avatar_url"]:
            person_embed.set_thumbnail(
                url=user["avatar_url"]
            )

        await interaction.channel.send(
            embed=person_embed
        )

    # =====================================================
    # PĂSTRĂM PANoul
    # =====================================================

    # Actualizăm panoul astfel încât să arate că sesiunea s-a terminat.
    await update_panel()

    # Răspuns invizibil pentru administrator
    await interaction.followup.send(
        "Prezența a fost încheiată și raportul a fost generat.",
        ephemeral=True
    )


# =========================================================
# PREZENȚA MEA
# =========================================================

@bot.tree.command(
    name="prezenta",
    description="Vezi dacă ești trecut prezent în sesiunea curentă."
)
async def prezenta(interaction: discord.Interaction):

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
            "❌ Nu ești trecut prezent.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        (
            "🟢 **Ești prezent.**\n"
            f"Prezent de la: `{format_datetime(row['started_at'])}`\n"
            f"Durată: `{format_duration(row['started_at'])}`"
        ),
        ephemeral=True
    )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print(f"Bot conectat ca {bot.user}")
    print(f"Timezone: {TIMEZONE_NAME}")
    print(f"Database: {DB_FILE}")

    # Persistent button
    bot.add_view(PresenceView())

    try:
        synced = await bot.tree.sync()
        print(f"Comenzi sincronizate: {len(synced)}")
    except Exception as e:
        print(f"Eroare la sincronizarea comenzilor: {e}")


# =========================================================
# START
# =========================================================

init_db()

bot.run(TOKEN)