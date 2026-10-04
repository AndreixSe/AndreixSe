import os
import re
import sqlite3
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

DB_PATH = "/data/pontaj.db"

# Dacă rulezi local și nu există /data
if not os.path.exists("/data"):
    DB_PATH = "pontaj.db"


# =========================================================
# DISCORD
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
    """
    Creează tabelele dacă nu există și repară schema veche
    fără să șteargă datele existente.
    """

    conn = get_db()
    cur = conn.cursor()

    # -----------------------------------------------------
    # SETTINGS
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            started_at TEXT,
            ended_at TEXT
        )
    """)

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

    # Verificăm coloanele existente în patrols
    cur.execute("PRAGMA table_info(patrols)")
    patrol_columns = [row["name"] for row in cur.fetchall()]

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

    # Citim schema existentă
    cur.execute("PRAGMA table_info(patrol_people)")
    patrol_people_info = cur.fetchall()

    patrol_people_columns = [
        row["name"] for row in patrol_people_info
    ]

    # -----------------------------------------------------
    # REPARĂM SCHEMA VECHE
    # -----------------------------------------------------

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

    # Dacă există display_name dar user_name este NULL,
    # copiem display_name în user_name.
    cur.execute("""
        UPDATE patrol_people
        SET user_name = display_name
        WHERE user_name IS NULL
          AND display_name IS NOT NULL
    """)

    # Dacă există user_name dar display_name este NULL,
    # copiem user_name în display_name.
    cur.execute("""
        UPDATE patrol_people
        SET display_name = user_name
        WHERE display_name IS NULL
          AND user_name IS NOT NULL
    """)

    # Dacă există user_id dar mention este NULL,
    # construim automat mention-ul Discord.
    cur.execute("""
        UPDATE patrol_people
        SET mention = '<@' || user_id || '>'
        WHERE mention IS NULL
          AND user_id IS NOT NULL
    """)

    # -----------------------------------------------------
    # DEFAULT SETTINGS
    # -----------------------------------------------------

    defaults = {
        "patrol_panel_channel_id": "",
        "patrol_panel_message_id": "",
        "attendance_panel_channel_id": "",
        "attendance_panel_message_id": "",
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


# =========================================================
# PATROL DATABASE FUNCTIONS
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


# =========================================================
# MENTION PARSING
# =========================================================

def parse_user_mentions(text):
    """
    Primește ceva de forma:

    <@123456789> <@987654321> <@555555555>

    și returnează ID-urile.
    """

    if not text:
        return []

    matches = re.findall(
        r"<@!?(\d+)>",
        text
    )

    # Eliminăm duplicatele păstrând ordinea
    result = []

    for user_id in matches:
        user_id = int(user_id)

        if user_id not in result:
            result.append(user_id)

    return result


# =========================================================
# PATROL EMBED
# =========================================================

def create_patrol_embed(patrol):
    people = get_patrol_people(patrol["id"])

    people_lines = []

    for person in people:
        mention = person["mention"]

        if not mention:
            mention = f"<@{person['user_id']}>"

        people_lines.append(mention)

    if people_lines:
        people_text = "\n".join(people_lines)
    else:
        people_text = "Nicio persoană"

    status = "🟢 PATRULĂ ACTIVĂ"

    if patrol["active"] == 0:
        status = "🔴 PATRULĂ ÎNCHEIATĂ"

    embed = discord.Embed(
        title="🚓 PATRULĂ",
        description=status,
        color=discord.Color.blue()
    )

    embed.add_field(
        name="👥 PERSOANE",
        value=people_text,
        inline=False
    )

    embed.add_field(
        name="📅 DATA",
        value=patrol["patrol_date"] or "-",
        inline=True
    )

    embed.add_field(
        name="🕐 ORA",
        value=patrol["patrol_time"] or "-",
        inline=True
    )

    embed.add_field(
        name="🚗 NR AUTO",
        value=str(patrol["cars_count"] or 0),
        inline=True
    )

    embed.add_field(
        name="🎨 CULOARE",
        value=patrol["color"] or "-",
        inline=False
    )

    embed.add_field(
        name="👤 NR PERS",
        value=str(len(people)),
        inline=True
    )

    if patrol["image_url"]:
        embed.add_field(
            name="📸 POZA",
            value=f"[Vezi poza în rezoluție completă]({patrol['image_url']})",
            inline=False
        )

        embed.set_image(
            url=patrol["image_url"]
        )

    embed.set_footer(
        text=f"Patrulă #{patrol['id']}"
    )

    return embed


# =========================================================
# SAVE PHOTO
# =========================================================

async def save_patrol_image(channel, attachment):
    """
    Copiază poza în canalul panoului.

    Asta este important deoarece linkul original Discord
    poate deveni indisponibil după expirarea attachment-ului.
    """

    if attachment is None:
        return None

    try:
        file = await attachment.to_file()

        message = await channel.send(
            content="📸 Poza patrulei",
            file=file
        )

        if message.attachments:
            return message.attachments[0].url

    except Exception as e:
        print(f"❌ Eroare salvare poza: {e}")

    return None


# =========================================================
# PATROL PANEL
# =========================================================

async def update_patrol_panel():
    channel_id = get_setting(
        "patrol_panel_channel_id"
    )

    message_id = get_setting(
        "patrol_panel_message_id"
    )

    if not channel_id or not message_id:
        return

    try:
        channel = bot.get_channel(
            int(channel_id)
        )

        if channel is None:
            return

        message = await channel.fetch_message(
            int(message_id)
        )

    except Exception as e:
        print(
            f"❌ Nu pot accesa panoul patrulei: {e}"
        )
        return

    patrol = get_active_patrol()

    if patrol is None:
        embed = discord.Embed(
            title="🚓 PATRULE",
            description="Nu există nicio patrulă activă.",
            color=discord.Color.dark_grey()
        )

        await message.edit(
            embed=embed,
            view=PatrolView()
        )

        return

    embed = create_patrol_embed(patrol)

    await message.edit(
        embed=embed,
        view=PatrolView()
    )


# =========================================================
# PATROL VIEW
# =========================================================

class PatrolView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Vezi patrula",
        style=discord.ButtonStyle.primary,
        emoji="🚓",
        custom_id="patrol_view_button"
    )
    async def view_patrol(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        patrol = get_active_patrol()

        if patrol is None:
            await interaction.response.send_message(
                "❌ Nu există nicio patrulă activă.",
                ephemeral=True
            )
            return

        embed = create_patrol_embed(patrol)

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# =========================================================
# ATTENDANCE
# =========================================================

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
        title="🕐 PONTAJ",
        color=discord.Color.green()
    )

    if not rows:
        embed.description = "Nu este nimeni pontat momentan."
        return embed

    lines = []

    for row in rows:
        lines.append(
            f"👤 <@{row['user_id']}> — "
            f"🟢 {row['started_at']}"
        )

    embed.description = "\n".join(lines)

    return embed


class AttendanceView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Începe pontaj",
        style=discord.ButtonStyle.success,
        emoji="🟢",
        custom_id="attendance_start"
    )
    async def start_attendance(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM attendance WHERE user_id = ?",
            (interaction.user.id,)
        )

        existing = cur.fetchone()

        if existing:
            conn.close()

            await interaction.response.send_message(
                "❌ Ești deja pontat.",
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
            interaction.user.id,
            interaction.user.display_name,
            now_string()
        ))

        conn.commit()
        conn.close()

        await update_attendance_panel()

        await interaction.response.send_message(
            "✅ Ai început pontajul.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Încheie pontaj",
        style=discord.ButtonStyle.danger,
        emoji="🔴",
        custom_id="attendance_stop"
    )
    async def stop_attendance(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM attendance WHERE user_id = ?",
            (interaction.user.id,)
        )

        existing = cur.fetchone()

        if not existing:
            conn.close()

            await interaction.response.send_message(
                "❌ Nu ești pontat.",
                ephemeral=True
            )
            return

        ended_at = now_string()

        cur.execute("""
            INSERT INTO attendance_history(
                user_id,
                user_name,
                started_at,
                ended_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            existing["user_id"],
            existing["user_name"],
            existing["started_at"],
            ended_at
        ))

        cur.execute(
            "DELETE FROM attendance WHERE user_id = ?",
            (interaction.user.id,)
        )

        conn.commit()
        conn.close()

        await update_attendance_panel()

        await interaction.response.send_message(
            "✅ Ai încheiat pontajul.",
            ephemeral=True
        )


async def update_attendance_panel():
    channel_id = get_setting(
        "attendance_panel_channel_id"
    )

    message_id = get_setting(
        "attendance_panel_message_id"
    )

    if not channel_id or not message_id:
        return

    try:
        channel = bot.get_channel(
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
        print(
            f"❌ Eroare panou pontaj: {e}"
        )


# =========================================================
# SETUP PONTAJ
# =========================================================

@bot.tree.command(
    name="setup_pontaj",
    description="Creează panoul de pontaj în canalul curent."
)
async def setup_pontaj(
    interaction: discord.Interaction
):

    embed = create_attendance_embed()

    message = await interaction.channel.send(
        embed=embed,
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
    description="Creează panoul de patrule în canalul curent."
)
async def setup_patrule(
    interaction: discord.Interaction
):

    embed = discord.Embed(
        title="🚓 PATRULE",
        description="Nu există nicio patrulă activă.",
        color=discord.Color.dark_grey()
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
# ÎNCEPE PATRULA
# =========================================================

@bot.tree.command(
    name="incepe_patrula",
    description="Începe o patrulă."
)
@app_commands.describe(
    persoane="Menționează persoanele: @Ion @Vasile @Andrei",
    data="Data, exemplu: 04.10.2026",
    ora="Ora, exemplu: 18:00",
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
    # VERIFICĂM DACĂ EXISTĂ PATRULĂ ACTIVĂ
    # -----------------------------------------------------

    active_patrol = get_active_patrol()

    if active_patrol:
        await interaction.followup.send(
            "❌ Există deja o patrulă activă. "
            "Încheie patrula actuală înainte să începi alta.",
            ephemeral=True
        )
        return

    # -----------------------------------------------------
    # PARSĂM MENTIONURILE
    # -----------------------------------------------------

    user_ids = parse_user_mentions(
        persoane
    )

    if not user_ids:
        await interaction.followup.send(
            "❌ Nu am găsit nicio mențiune validă.\n\n"
            "Folosește persoanele prin mențiune Discord, "
            "de exemplu: `@Ion @Vasile @Andrei`.",
            ephemeral=True
        )
        return

    # -----------------------------------------------------
    # VERIFICĂM MEMBRII
    # -----------------------------------------------------

    members = []

    for user_id in user_ids:

        member = interaction.guild.get_member(
            user_id
        )

        if member is None:
            try:
                member = await interaction.guild.fetch_member(
                    user_id
                )
            except Exception:
                member = None

        if member is None:
            continue

        members.append(member)

    if not members:
        await interaction.followup.send(
            "❌ Nu am putut găsi membrii menționați pe server.",
            ephemeral=True
        )
        return

    # -----------------------------------------------------
    # VERIFICĂM NR AUTO
    # -----------------------------------------------------

    if nr_auto < 1:
        await interaction.followup.send(
            "❌ Numărul de mașini trebuie să fie cel puțin 1.",
            ephemeral=True
        )
        return

    # -----------------------------------------------------
    # VERIFICĂM POZA
    # -----------------------------------------------------

    if poza is not None:

        allowed_types = [
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/webp"
        ]

        if poza.content_type not in allowed_types:
            await interaction.followup.send(
                "❌ Poza trebuie să fie PNG, JPG, JPEG sau WEBP.",
                ephemeral=True
            )
            return

    # -----------------------------------------------------
    # CANAL PANOU
    # -----------------------------------------------------

    panel_channel_id = get_setting(
        "patrol_panel_channel_id"
    )

    if not panel_channel_id:
        await interaction.followup.send(
            "❌ Panoul de patrule nu este configurat.\n"
            "Rulează mai întâi `/setup_patrule`.",
            ephemeral=True
        )
        return

    panel_channel = bot.get_channel(
        int(panel_channel_id)
    )

    if panel_channel is None:
        await interaction.followup.send(
            "❌ Nu am găsit canalul panoului de patrule.",
            ephemeral=True
        )
        return

    # -----------------------------------------------------
    # SALVĂM POZA
    # -----------------------------------------------------

    image_url = None

    if poza is not None:
        image_url = await save_patrol_image(
            panel_channel,
            poza
        )

    # -----------------------------------------------------
    # CREĂM PATRULA
    # -----------------------------------------------------

    conn = get_db()
    cur = conn.cursor()

    started_at = now_string()

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
        started_at,
        None,
        interaction.user.id,
        interaction.user.display_name,
        1
    ))

    patrol_id = cur.lastrowid

    # -----------------------------------------------------
    # SALVĂM PERSOANELE
    #
    # IMPORTANT:
    # display_name este inclus pentru baza veche.
    # -----------------------------------------------------

    for member in members:

        user_name = member.display_name
        display_name = member.display_name
        mention = member.mention

        cur.execute("""
            INSERT INTO patrol_people(
                patrol_id,
                user_id,
                user_name,
                display_name,
                mention
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            patrol_id,
            member.id,
            user_name,
            display_name,
            mention
        ))

    conn.commit()
    conn.close()

    # -----------------------------------------------------
    # ACTUALIZĂM PANOU
    # -----------------------------------------------------

    await update_patrol_panel()

    # -----------------------------------------------------
    # CONFIRMARE
    # -----------------------------------------------------

    mentions_text = " ".join(
        member.mention
        for member in members
    )

    await interaction.followup.send(
        "✅ **Patrula a fost începută cu succes!**\n\n"
        f"👥 Persoane: {mentions_text}\n"
        f"📅 Data: {data}\n"
        f"🕐 Ora: {ora}\n"
        f"🚗 Nr auto: {nr_auto}\n"
        f"🎨 Culoare: {culoare}\n"
        f"👤 Nr pers: {len(members)}",
        ephemeral=True
    )


# =========================================================
# ÎNCHEIE PATRULA
# =========================================================

@bot.tree.command(
    name="incheie_patrula",
    description="Încheie patrula activă."
)
async def incheie_patrula(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    patrol = get_active_patrol()

    if patrol is None:
        await interaction.followup.send(
            "❌ Nu există nicio patrulă activă.",
            ephemeral=True
        )
        return

    ended_at = now_string()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE patrols
        SET
            active = 0,
            ended_at = ?
        WHERE id = ?
    """, (
        ended_at,
        patrol["id"]
    ))

    conn.commit()

    # Luăm din nou patrula după update
    cur.execute(
        "SELECT * FROM patrols WHERE id = ?",
        (patrol["id"],)
    )

    updated_patrol = cur.fetchone()

    conn.close()

    # -----------------------------------------------------
    # ACTUALIZĂM PANOU
    # -----------------------------------------------------

    await update_patrol_panel()

    # -----------------------------------------------------
    # AFIȘĂM CONFIRMAREA
    # -----------------------------------------------------

    embed = create_patrol_embed(
        updated_patrol
    )

    await interaction.followup.send(
        content="🔴 **Patrula a fost încheiată.**",
        embed=embed,
        ephemeral=True
    )


# =========================================================
# VEZI PATRULA
# =========================================================

@bot.tree.command(
    name="patrula",
    description="Afișează patrula activă."
)
async def patrula(
    interaction: discord.Interaction
):

    patrol = get_active_patrol()

    if patrol is None:
        await interaction.response.send_message(
            "❌ Nu există nicio patrulă activă.",
            ephemeral=True
        )
        return

    embed = create_patrol_embed(
        patrol
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# =========================================================
# ISTORIC PATRULE
# =========================================================

@bot.tree.command(
    name="istoric_patrule",
    description="Afișează ultimele patrule."
)
async def istoric_patrule(
    interaction: discord.Interaction
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM patrols
        ORDER BY id DESC
        LIMIT 10
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message(
            "❌ Nu există patrule înregistrate.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="📋 ISTORIC PATRULE",
        color=discord.Color.blue()
    )

    for patrol in rows:

        status = "🟢 ACTIVĂ" if patrol["active"] else "🔴 ÎNCHEIATĂ"

        embed.add_field(
            name=f"🚓 Patrula #{patrol['id']} — {status}",
            value=(
                f"📅 {patrol['patrol_date'] or '-'}\n"
                f"🕐 {patrol['patrol_time'] or '-'}\n"
                f"🚗 Auto: {patrol['cars_count'] or 0}\n"
                f"👤 Persoane: {patrol['people_count'] or 0}\n"
                f"🎨 {patrol['color'] or '-'}"
            ),
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# =========================================================
# PONTAJ COMANDĂ
# =========================================================

@bot.tree.command(
    name="pontaj",
    description="Afișează pontajul actual."
)
async def pontaj(
    interaction: discord.Interaction
):

    embed = create_attendance_embed()

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# =========================================================
# ISTORIC PONTAJ
# =========================================================

@bot.tree.command(
    name="istoric_pontaj",
    description="Afișează istoricul pontajului."
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
        LIMIT 20
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message(
            "❌ Nu există istoric de pontaj.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="📋 ISTORIC PONTAJ",
        color=discord.Color.green()
    )

    for row in rows:

        embed.add_field(
            name=f"👤 {row['user_name']}",
            value=(
                f"🟢 Început: {row['started_at']}\n"
                f"🔴 Sfârșit: {row['ended_at']}"
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

    print("========================================")
    print(f"🤖 Bot conectat ca {bot.user}")
    print("========================================")

    # -----------------------------------------------------
    # COMENZI SLASH
    # -----------------------------------------------------

    try:
        synced = await bot.tree.sync()

        print(
            f"✅ Comenzi sincronizate: {len(synced)}"
        )

    except Exception as e:

        print(
            f"❌ Eroare sincronizare comenzi: {e}"
        )

    # -----------------------------------------------------
    # PERSISTENT VIEWS
    # -----------------------------------------------------

    try:
        bot.add_view(
            PatrolView()
        )

        bot.add_view(
            AttendanceView()
        )

        print(
            "✅ Butoanele persistente au fost încărcate."
        )

    except Exception as e:

        print(
            f"❌ Eroare persistent views: {e}"
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
        f"❌ App command error: {repr(error)}"
    )

    # Dacă este deja CommandInvokeError,
    # afișăm cauza reală.
    if isinstance(
        error,
        app_commands.CommandInvokeError
    ):
        print(
            f"❌ Cauza reală: {repr(error.original)}"
        )

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                "❌ A apărut o eroare la executarea comenzii. "
                "Verifică logurile Railway.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "❌ A apărut o eroare la executarea comenzii. "
                "Verifică logurile Railway.",
                ephemeral=True
            )

    except Exception:
        pass


# =========================================================
# START
# =========================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN nu este setat."
    )


# Foarte important:
# Migrarea se face ÎNAINTE să pornească botul.
migrate_database()

bot.run(TOKEN)