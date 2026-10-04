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

if not TOKEN:
    raise RuntimeError("Lipseste DISCORD_TOKEN din variabilele de mediu.")

try:
    TZ = ZoneInfo(TIMEZONE)
except Exception:
    TZ = ZoneInfo("Europe/Bucharest")

if os.path.exists("/data"):
    DB_PATH = "/data/pontaj.db"
else:
    DB_PATH = "pontaj.db"


# =========================================================
# BOT
# =========================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_database():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            user_id INTEGER PRIMARY KEY,
            user_name TEXT,
            started_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            started_at TEXT,
            ended_at TEXT
        )
    """)

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

       cur.execute("""
        CREATE TABLE IF NOT EXISTS patrol_people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patrol_id INTEGER,
            user_id INTEGER
        )
    """)

    # =====================================================
    # MIGRARE AUTOMATA patrol_people
    # =====================================================

    cur.execute("PRAGMA table_info(patrol_people)")
    patrol_people_columns = [
        row["name"] for row in cur.fetchall()
    ]

    if "user_name" not in patrol_people_columns:
        cur.execute("""
            ALTER TABLE patrol_people
            ADD COLUMN user_name TEXT
        """)

    if "mention" not in patrol_people_columns:
        cur.execute("""
            ALTER TABLE patrol_people
            ADD COLUMN mention TEXT
        """)
        )
    """)

    # -----------------------------------------------------
    # Verificam daca baza veche are image_url
    # -----------------------------------------------------

    cur.execute("PRAGMA table_info(patrols)")
    patrol_columns = [row["name"] for row in cur.fetchall()]

    if "image_url" not in patrol_columns:
        cur.execute(
            "ALTER TABLE patrols ADD COLUMN image_url TEXT"
        )

    # -----------------------------------------------------
    # Setari implicite
    # -----------------------------------------------------

    defaults = {
        "patrol_panel_channel_id": "",
        "patrol_panel_message_id": "",
        "attendance_panel_channel_id": "",
        "attendance_panel_message_id": "",
    }

    for key, value in defaults.items():
        cur.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
            (key, value)
        )

    conn.commit()
    conn.close()


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
    return datetime.now(TZ)


def now_string():
    return now().strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
# PATROL HELPERS
# =========================================================

def get_active_patrol():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM patrols
        WHERE active = 1
        ORDER BY id DESC
        LIMIT 1
    """)

    row = cur.fetchone()
    conn.close()

    return row


def get_patrol_people(patrol_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM patrol_people
        WHERE patrol_id = ?
        ORDER BY id ASC
    """, (patrol_id,))

    rows = cur.fetchall()
    conn.close()

    return rows


def parse_user_mentions(text, guild):
    """
    Primeste ceva de genul:

    @Ion @Vasile @Andrei

    si returneaza membrii reali ai serverului.
    """

    if not text:
        return []

    members = []

    # Discord poate trimite mentionurile sub forma:
    # <@123456789>
    # <@!123456789>

    ids = re.findall(r"<@!?(\d+)>", text)

    already_added = set()

    for user_id in ids:
        user_id = int(user_id)

        if user_id in already_added:
            continue

        member = guild.get_member(user_id)

        if member:
            members.append(member)
            already_added.add(user_id)

    return members


def build_mentions_text(people):
    """
    Afiseaza mentiunile reale Discord.
    """

    if not people:
        return "Nicio persoana"

    return "\n".join(
        f"<@{person['user_id']}>"
        for person in people
    )


def create_patrol_embed(patrol):
    people = get_patrol_people(patrol["id"])

    embed = discord.Embed(
        title="🚔 PATRULĂ",
        description="",
        color=discord.Color.dark_purple()
    )

    # =====================================================
    # PERSOANE
    # =====================================================

    mentions = build_mentions_text(people)

    embed.add_field(
        name="👥 PERSOANE",
        value=mentions,
        inline=False
    )

    # =====================================================
    # DATA
    # =====================================================

    embed.add_field(
        name="📅 DATA",
        value=patrol["patrol_date"] or "-",
        inline=True
    )

    # =====================================================
    # ORA
    # =====================================================

    embed.add_field(
        name="🕐 ORA",
        value=patrol["patrol_time"] or "-",
        inline=True
    )

    # =====================================================
    # NR AUTO
    # =====================================================

    embed.add_field(
        name="🚗 NR AUTO",
        value=str(patrol["cars_count"]),
        inline=True
    )

    # =====================================================
    # CULOARE
    # =====================================================

    embed.add_field(
        name="🎨 CULOARE",
        value=patrol["color"] or "-",
        inline=False
    )

    # =====================================================
    # NR PERS
    # =====================================================

    embed.add_field(
        name="👤 NR PERS",
        value=str(len(people)),
        inline=True
    )

    # =====================================================
    # POZA
    # =====================================================

    if patrol["image_url"]:
        embed.add_field(
            name="📸 POZA",
            value=f"[🖼️ Deschide poza la rezoluție completă]({patrol['image_url']})",
            inline=False
        )

        embed.set_image(url=patrol["image_url"])
    else:
        embed.add_field(
            name="📸 POZA",
            value="Nu a fost încărcată nicio poză.",
            inline=False
        )

    # =====================================================
    # STATUS
    # =====================================================

    if patrol["active"]:
        embed.set_footer(
            text="🟢 PATRULĂ ACTIVĂ"
        )
    else:
        embed.set_footer(
            text="🔴 PATRULĂ ÎNCHEIATĂ"
        )

    return embed


# =========================================================
# SAVE PATROL IMAGE
# =========================================================

async def save_patrol_image(interaction, attachment):
    """
    Face o copie a pozei într-un mesaj Discord permanent.
    Folosim URL-ul atasamentului copiat pentru embed.
    """

    if not attachment:
        return None

    channel_id = get_setting("patrol_panel_channel_id")

    channel = None

    if channel_id:
        try:
            channel = interaction.guild.get_channel(
                int(channel_id)
            )
        except Exception:
            channel = None

    if channel is None:
        channel = interaction.channel

    if channel is None:
        return None

    try:
        file = await attachment.to_file()

        photo_message = await channel.send(
            content="📸 Poză patrulă",
            file=file
        )

        if not photo_message.attachments:
            return None

        saved_attachment = photo_message.attachments[0]

        return saved_attachment.url

    except Exception as e:
        print("Eroare la salvarea pozei:", e)
        return None


# =========================================================
# UPDATE PATROL PANEL
# =========================================================

async def update_patrol_panel(guild):
    patrol = get_active_patrol()

    if not patrol:
        return

    channel_id = get_setting("patrol_panel_channel_id")
    message_id = get_setting("patrol_panel_message_id")

    if not channel_id or not message_id:
        return

    try:
        channel = guild.get_channel(int(channel_id))

        if channel is None:
            return

        message = await channel.fetch_message(
            int(message_id)
        )

        embed = create_patrol_embed(patrol)

        await message.edit(
            embed=embed,
            view=PatrolView()
        )

    except Exception as e:
        print("Eroare update panou patrula:", e)


# =========================================================
# PATROL VIEW
# =========================================================

class PatrolView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🚔 Patrulă activă",
        style=discord.ButtonStyle.success,
        custom_id="patrol_status_button"
    )
    async def patrol_status(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        patrol = get_active_patrol()

        if not patrol:
            await interaction.response.send_message(
                "❌ Nu există nicio patrulă activă.",
                ephemeral=True
            )
            return

        people = get_patrol_people(patrol["id"])

        mentions = build_mentions_text(people)

        await interaction.response.send_message(
            f"🚔 **PATRULĂ ACTIVĂ**\n\n"
            f"👥 **PERSOANE:**\n{mentions}\n\n"
            f"📅 **DATA:** {patrol['patrol_date']}\n"
            f"🕐 **ORA:** {patrol['patrol_time']}\n"
            f"🚗 **NR AUTO:** {patrol['cars_count']}\n"
            f"🎨 **CULOARE:** {patrol['color']}\n"
            f"👤 **NR PERS:** {len(people)}",
            ephemeral=True
        )


# =========================================================
# ATTENDANCE
# =========================================================

class AttendanceView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🟢 Intră în tură",
        style=discord.ButtonStyle.success,
        custom_id="attendance_start"
    )
    async def start_attendance(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        user = interaction.user

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM attendance WHERE user_id = ?",
            (user.id,)
        )

        existing = cur.fetchone()

        if existing:
            conn.close()

            await interaction.response.send_message(
                "⚠️ Ești deja pontat.",
                ephemeral=True
            )
            return

        cur.execute("""
            INSERT INTO attendance(
                user_id,
                user_name,
                started_at
            )
            VALUES (?, ?, ?)
        """, (
            user.id,
            user.display_name,
            now_string()
        ))

        conn.commit()
        conn.close()

        await interaction.response.send_message(
            "🟢 Ai intrat în tură.",
            ephemeral=True
        )

        await update_attendance_panel(interaction.guild)

    @discord.ui.button(
        label="🔴 Ieși din tură",
        style=discord.ButtonStyle.danger,
        custom_id="attendance_end"
    )
    async def end_attendance(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        user = interaction.user

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM attendance WHERE user_id = ?",
            (user.id,)
        )

        existing = cur.fetchone()

        if not existing:
            conn.close()

            await interaction.response.send_message(
                "⚠️ Nu ești pontat.",
                ephemeral=True
            )
            return

        ended = now_string()

        cur.execute("""
            INSERT INTO attendance_history(
                user_id,
                user_name,
                started_at,
                ended_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            user.id,
            existing["user_name"],
            existing["started_at"],
            ended
        ))

        cur.execute(
            "DELETE FROM attendance WHERE user_id = ?",
            (user.id,)
        )

        conn.commit()
        conn.close()

        await interaction.response.send_message(
            "🔴 Ai ieșit din tură.",
            ephemeral=True
        )

        await update_attendance_panel(interaction.guild)


def create_attendance_embed():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM attendance
        ORDER BY started_at ASC
    """)

    rows = cur.fetchall()
    conn.close()

    embed = discord.Embed(
        title="📋 PONTAJ",
        color=discord.Color.green()
    )

    if not rows:
        embed.description = "Nu este nimeni pontat momentan."
        return embed

    text = ""

    for row in rows:
        text += (
            f"🟢 <@{row['user_id']}>"
            f" — din {row['started_at']}\n"
        )

    embed.description = text

    return embed


async def update_attendance_panel(guild):
    channel_id = get_setting(
        "attendance_panel_channel_id"
    )

    message_id = get_setting(
        "attendance_panel_message_id"
    )

    if not channel_id or not message_id:
        return

    try:
        channel = guild.get_channel(
            int(channel_id)
        )

        if channel is None:
            return

        message = await channel.fetch_message(
            int(message_id)
        )

        await message.edit(
            embed=create_attendance_embed(),
            view=AttendanceView()
        )

    except Exception as e:
        print("Eroare update panou pontaj:", e)


# =========================================================
# SETUP PONTAJ
# =========================================================

@bot.tree.command(
    name="setup_pontaj",
    description="Creează panoul de pontaj."
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_pontaj(
    interaction: discord.Interaction
):
    message = await interaction.channel.send(
        embed=create_attendance_embed(),
        view=AttendanceView()
    )

    set_setting(
        "attendance_panel_channel_id",
        str(interaction.channel.id)
    )

    set_setting(
        "attendance_panel_message_id",
        str(message.id)
    )

    await interaction.response.send_message(
        "✅ Panoul de pontaj a fost creat.",
        ephemeral=True
    )


# =========================================================
# SETUP PATRULE
# =========================================================

@bot.tree.command(
    name="setup_patrule",
    description="Creează panoul de patrule."
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_patrule(
    interaction: discord.Interaction
):
    embed = discord.Embed(
        title="🚔 PATRULE",
        description=(
            "Folosește `/incepe_patrula` pentru a începe o patrulă.\n"
            "Folosește `/incheie_patrula` pentru a o încheia."
        ),
        color=discord.Color.dark_purple()
    )

    message = await interaction.channel.send(
        embed=embed,
        view=PatrolView()
    )

    set_setting(
        "patrol_panel_channel_id",
        str(interaction.channel.id)
    )

    set_setting(
        "patrol_panel_message_id",
        str(message.id)
    )

    await interaction.response.send_message(
        "✅ Panoul de patrule a fost creat.",
        ephemeral=True
    )


# =========================================================
# INCEPE PATRULA
# =========================================================

@bot.tree.command(
    name="incepe_patrula",
    description="Începe o patrulă."
)
@app_commands.describe(
    persoane="Menționează persoanele care vin la patrulă: @Ion @Vasile @Andrei",
    data="Data patrulei, de exemplu 04.10.2026",
    ora="Ora patrulei, de exemplu 18:00",
    nr_auto="Numărul de mașini",
    culoare="Culoarea mașinilor",
    poza="Poza patrulei"
)
async def incepe_patrula(
    interaction: discord.Interaction,
    persoane: str,
    data: str,
    ora: str,
    nr_auto: int,
    culoare: str,
    poza: discord.Attachment = None
):
    await interaction.response.defer(
        ephemeral=True
    )

    # -----------------------------------------------------
    # Verificam daca exista deja o patrula
    # -----------------------------------------------------

    existing = get_active_patrol()

    if existing:
        await interaction.followup.send(
            "❌ Există deja o patrulă activă. "
            "Încheie patrula actuală înainte să începi alta.",
            ephemeral=True
        )
        return

    # -----------------------------------------------------
    # Extragem mentionurile reale
    # -----------------------------------------------------

    members = parse_user_mentions(
        persoane,
        interaction.guild
    )

    if not members:
        await interaction.followup.send(
            "❌ Nu am găsit nicio mențiune Discord.\n\n"
            "Scrie persoanele astfel:\n"
            "`@Ion @Vasile @Andrei`",
            ephemeral=True
        )
        return

    # -----------------------------------------------------
    # Salvam poza
    # -----------------------------------------------------

    image_url = None

    if poza:
        allowed_types = {
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/webp",
            "image/gif"
        }

        if poza.content_type and poza.content_type not in allowed_types:
            await interaction.followup.send(
                "❌ Fișierul încărcat nu este o imagine.",
                ephemeral=True
            )
            return

        image_url = await save_patrol_image(
            interaction,
            poza
        )

        if not image_url:
            await interaction.followup.send(
                "❌ Nu am putut salva poza. "
                "Verifică dacă botul are permisiunea **Attach Files**.",
                ephemeral=True
            )
            return

    # -----------------------------------------------------
    # Cream patrula
    # -----------------------------------------------------

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO patrols(
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "Patrulă",
        len(members),
        nr_auto,
        culoare,
        data,
        ora,
        image_url,
        now_string(),
        None,
        interaction.user.id,
        interaction.user.display_name,
        1
    ))

    patrol_id = cur.lastrowid

    # -----------------------------------------------------
    # Salvam fiecare persoana
    # -----------------------------------------------------

    for member in members:
        cur.execute("""
            INSERT INTO patrol_people(
                patrol_id,
                user_id,
                user_name,
                mention
            )
            VALUES (?, ?, ?, ?)
        """, (
            patrol_id,
            member.id,
            member.display_name,
            f"<@{member.id}>"
        ))

    conn.commit()
    conn.close()

    # -----------------------------------------------------
    # Actualizam panoul
    # -----------------------------------------------------

    await update_patrol_panel(
        interaction.guild
    )

    # -----------------------------------------------------
    # Confirmare
    # -----------------------------------------------------

    mentions = " ".join(
        member.mention
        for member in members
    )

    await interaction.followup.send(
        "✅ **Patrula a fost începută!**\n\n"
        f"👥 **PERSOANE:** {mentions}\n"
        f"📅 **DATA:** {data}\n"
        f"🕐 **ORA:** {ora}\n"
        f"🚗 **NR AUTO:** {nr_auto}\n"
        f"🎨 **CULOARE:** {culoare}\n"
        f"👤 **NR PERS:** {len(members)}",
        ephemeral=True
    )


# =========================================================
# INCHEIE PATRULA
# =========================================================

@bot.tree.command(
    name="incheie_patrula",
    description="Încheie patrula activă."
)
async def incheie_patrula(
    interaction: discord.Interaction
):
    patrol = get_active_patrol()

    if not patrol:
        await interaction.response.send_message(
            "❌ Nu există nicio patrulă activă.",
            ephemeral=True
        )
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE patrols
        SET active = 0,
            ended_at = ?
        WHERE id = ?
    """, (
        now_string(),
        patrol["id"]
    ))

    conn.commit()
    conn.close()

    # Panoul principal trebuie actualizat
    channel_id = get_setting(
        "patrol_panel_channel_id"
    )

    message_id = get_setting(
        "patrol_panel_message_id"
    )

    if channel_id and message_id:
        try:
            channel = interaction.guild.get_channel(
                int(channel_id)
            )

            message = await channel.fetch_message(
                int(message_id)
            )

            old_embed = create_patrol_embed(
                patrol
            )

            old_embed.color = discord.Color.red()

            old_embed.set_footer(
                text="🔴 PATRULĂ ÎNCHEIATĂ"
            )

            await message.edit(
                embed=old_embed,
                view=PatrolView()
            )

        except Exception as e:
            print(
                "Eroare actualizare patrula incheiata:",
                e
            )

    await interaction.response.send_message(
        "🔴 **Patrula a fost încheiată.**",
        ephemeral=True
    )


# =========================================================
# PATRULA
# =========================================================

@bot.tree.command(
    name="patrula",
    description="Vezi patrula activă."
)
async def patrula(
    interaction: discord.Interaction
):
    patrol = get_active_patrol()

    if not patrol:
        await interaction.response.send_message(
            "❌ Nu există nicio patrulă activă.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        embed=create_patrol_embed(patrol),
        ephemeral=True
    )


# =========================================================
# ISTORIC PATRULE
# =========================================================

@bot.tree.command(
    name="istoric_patrule",
    description="Vezi istoricul patrulelor."
)
async def istoric_patrule(
    interaction: discord.Interaction
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
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
            created_by_id,
            created_by_name,
            active
        FROM patrols
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message(
            "📭 Nu există patrule în istoric.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="📜 ISTORIC PATRULE",
        color=discord.Color.dark_purple()
    )

    for row in rows:
        people = get_patrol_people(
            row["id"]
        )

        mentions = build_mentions_text(
            people
        )

        status = (
            "🟢 ACTIVĂ"
            if row["active"]
            else "🔴 ÎNCHEIATĂ"
        )

        value = (
            f"{status}\n"
            f"👥 **Persoane:**\n{mentions}\n"
            f"📅 **Data:** {row['patrol_date']}\n"
            f"🕐 **Ora:** {row['patrol_time']}\n"
            f"🚗 **Auto:** {row['cars_count']}\n"
            f"🎨 **Culoare:** {row['color']}\n"
            f"👤 **Nr pers:** {len(people)}"
        )

        if row["image_url"]:
            value += (
                f"\n📸 [Vezi poza]"
                f"({row['image_url']})"
            )

        embed.add_field(
            name=f"🚔 Patrula #{row['id']}",
            value=value,
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# =========================================================
# COMENZI PONTAJ SUPLIMENTARE
# =========================================================

@bot.tree.command(
    name="pontaj",
    description="Vezi cine este pontat."
)
async def pontaj(
    interaction: discord.Interaction
):
    await interaction.response.send_message(
        embed=create_attendance_embed(),
        ephemeral=True
    )


@bot.tree.command(
    name="istoric_pontaj",
    description="Vezi istoricul pontajului."
)
async def istoric_pontaj(
    interaction: discord.Interaction
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM attendance_history
        ORDER BY id DESC
        LIMIT 30
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message(
            "📭 Nu există istoric de pontaj.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="📜 ISTORIC PONTAJ",
        color=discord.Color.blue()
    )

    for row in rows:
        embed.add_field(
            name=row["user_name"],
            value=(
                f"🟢 Intrare: `{row['started_at']}`\n"
                f"🔴 Ieșire: `{row['ended_at']}`"
            ),
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():
    migrate_database()

    bot.add_view(PatrolView())
    bot.add_view(AttendanceView())

    try:
        synced = await bot.tree.sync()

        print(
            f"Bot conectat ca {bot.user}"
        )

        print(
            f"Comenzi sincronizate: {len(synced)}"
        )

    except Exception as e:
        print(
            "Eroare sincronizare comenzi:",
            e
        )


# =========================================================
# ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error
):
    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):
        message = (
            "❌ Nu ai permisiunea necesară "
            "pentru această comandă."
        )

    else:
        print(
            "App command error:",
            repr(error)
        )

        message = (
            "❌ A apărut o eroare la executarea comenzii."
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
# START
# =========================================================

migrate_database()

bot.run(TOKEN)