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
# ROLURI DONAȚII
# =========================================================

# Acces TOTAL la sistemul de donații:
# - /setup_donatii
# - /donatii
# - butonul ✅ PRIMITĂ
# - butonul ❌ NEPRIMITĂ
# - /donatie
DONATION_FULL_ACCESS_ROLE_IDS = {
    1527919721629089862,  # Co-Lider
    1528799552075989102,  # Lider
    1554072182735511623,  # Discord Mod
}


# Acces pentru CREAREA unei donații:
# - /donatie
DONATION_CREATE_ROLE_IDS = {
    1527919721629089862,  # Co-Lider
    1528799552075989102,  # Lider
    1554072182735511623,  # Discord Mod
    1528804522938597557,  # Miembro
}


def has_donation_full_access(
    interaction: discord.Interaction
) -> bool:

    if not interaction.guild:
        return False

    member = interaction.user

    if not isinstance(member, discord.Member):
        return False

    return any(
        role.id in DONATION_FULL_ACCESS_ROLE_IDS
        for role in member.roles
    )


def has_donation_create_access(
    interaction: discord.Interaction
) -> bool:

    if not interaction.guild:
        return False

    member = interaction.user

    if not isinstance(member, discord.Member):
        return False

    return any(
        role.id in DONATION_CREATE_ROLE_IDS
        for role in member.roles
    )


def donation_full_access_message():

    return (
        "❌ **Nu ai acces la această funcție.**\n\n"
        "Ai nevoie de unul dintre gradele:\n"
        "👑 **Lider**\n"
        "🛡️ **Co-Lider**\n"
        "🔧 **Discord Mod**"
    )


def donation_create_access_message():

    return (
        "❌ **Nu ai acces la această funcție.**\n\n"
        "Pentru a crea o donație ai nevoie de gradul:\n"
        "👤 **Miembro**\n\n"
        "Lider, Co-Lider și Discord Mod au de asemenea acces."
    )


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

    if not text:
        return []

    matches = re.findall(
        r"<@!?(\d+)>",
        text
    )

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

    people = get_patrol_people(
        patrol["id"]
    )

    people_lines = []

    for person in people:

        mention = person["mention"]

        if not mention:
            mention = f"<@{person['user_id']}>"

        people_lines.append(
            mention
        )

    if people_lines:
        people_text = "\n".join(
            people_lines
        )
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
            value=(
                f"[Vezi poza în rezoluție completă]"
                f"({patrol['image_url']})"
            ),
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

        print(
            f"❌ Eroare salvare poza: {e}"
        )

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

    embed = create_patrol_embed(
        patrol
    )

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

        embed = create_patrol_embed(
            patrol
        )

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

        embed.description = (
            "Nu este nimeni pontat momentan."
        )

        return embed

    lines = []

    for row in rows:

        lines.append(
            f"👤 <@{row['user_id']}> — "
            f"🟢 {row['started_at']}"
        )

    embed.description = "\n".join(
        lines
    )

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
# DONAȚII - DATABASE
# =========================================================

def get_donations():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM donations
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cur.fetchall()

    conn.close()

    return rows


def get_donation(donation_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM donations
        WHERE id = ?
    """, (donation_id,))

    row = cur.fetchone()

    conn.close()

    return row


# =========================================================
# DONAȚII - EMBED
# =========================================================

def create_donation_embed(donation):

    if donation["status"] == "received":

        status_text = "✅ PRIMITĂ"
        embed_color = discord.Color.green()

    else:

        status_text = "❌ NEPRIMITĂ"
        embed_color = discord.Color.red()

    donor_mention = (
        f"<@{donation['donor_id']}>"
    )

    embed = discord.Embed(
        title=f"🎁 DONAȚIA #{donation['id']}",
        color=embed_color
    )

    embed.add_field(
        name="👤 DONATOR",
        value=donor_mention,
        inline=False
    )

    embed.add_field(
        name="📦 OBIECTE",
        value=donation["items"] or "-",
        inline=False
    )

    embed.add_field(
        name="🔢 NUMĂR",
        value=str(
            donation["items_count"] or 0
        ),
        inline=True
    )

    embed.add_field(
        name="📌 STATUS",
        value=status_text,
        inline=True
    )

    embed.add_field(
        name="📅 DATA",
        value=donation["created_at"] or "-",
        inline=True
    )

    if donation["status"] == "received":

        embed.add_field(
            name="✅ PRIMITĂ DE",
            value=(
                donation["confirmed_by_name"]
                or "-"
            ),
            inline=False
        )

        embed.add_field(
            name="🕐 CONFIRMATĂ LA",
            value=(
                donation["confirmed_at"]
                or "-"
            ),
            inline=False
        )

    embed.set_footer(
        text="Sistem donații"
    )

    return embed


# =========================================================
# DONAȚII - VIEW
# =========================================================

class DonationItemView(discord.ui.View):

    def __init__(self, donation_id):

        super().__init__(
            timeout=None
        )

        self.donation_id = donation_id

        self.received_button.custom_id = (
            f"donation_received_{donation_id}"
        )

        self.not_received_button.custom_id = (
            f"donation_not_received_{donation_id}"
        )

    @discord.ui.button(
        label="PRIMITĂ",
        style=discord.ButtonStyle.success,
        emoji="✅"
    )
    async def received_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        # -------------------------------------------------
        # DOAR LIDER / CO-LIDER / DISCORD MOD
        # -------------------------------------------------

        if not has_donation_full_access(interaction):

            await interaction.response.send_message(
                donation_full_access_message(),
                ephemeral=True
            )

            return

        donation = get_donation(
            self.donation_id
        )

        if donation is None:

            await interaction.response.send_message(
                "❌ Donația nu mai există.",
                ephemeral=True
            )

            return

        if donation["status"] == "received":

            await interaction.response.send_message(
                "❌ Această donație este deja marcată ca primită.",
                ephemeral=True
            )

            return

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE donations
            SET
                status = 'received',
                confirmed_at = ?,
                confirmed_by_id = ?,
                confirmed_by_name = ?
            WHERE id = ?
        """, (
            now_string(),
            interaction.user.id,
            interaction.user.display_name,
            self.donation_id
        ))

        conn.commit()
        conn.close()

        updated_donation = get_donation(
            self.donation_id
        )

        try:

            await interaction.message.edit(
                embed=create_donation_embed(
                    updated_donation
                ),
                view=DonationItemView(
                    self.donation_id
                )
            )

        except Exception as e:

            print(
                f"❌ Eroare actualizare donație: {e}"
            )

        await interaction.response.send_message(
            f"✅ Donația #{self.donation_id} "
            f"a fost marcată ca **PRIMITĂ** de "
            f"{interaction.user.mention}.",
            ephemeral=True
        )

        await update_donation_panel()

    @discord.ui.button(
        label="NEPRIMITĂ",
        style=discord.ButtonStyle.danger,
        emoji="❌"
    )
    async def not_received_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        # -------------------------------------------------
        # DOAR LIDER / CO-LIDER / DISCORD MOD
        # -------------------------------------------------

        if not has_donation_full_access(interaction):

            await interaction.response.send_message(
                donation_full_access_message(),
                ephemeral=True
            )

            return

        donation = get_donation(
            self.donation_id
        )

        if donation is None:

            await interaction.response.send_message(
                "❌ Donația nu mai există.",
                ephemeral=True
            )

            return

        if donation["status"] == "received":

            await interaction.response.send_message(
                "❌ Donația este deja marcată ca primită.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            f"❌ Donația #{self.donation_id} "
            f"este în continuare **NEPRIMITĂ**.",
            ephemeral=True
        )


# =========================================================
# DONAȚII - PANOU
# =========================================================

async def update_donation_panel():

    channel_id = get_setting(
        "donation_panel_channel_id"
    )

    message_id = get_setting(
        "donation_panel_message_id"
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

        donations = get_donations()

        if not donations:

            embed = discord.Embed(
                title="🎁 DONAȚII",
                description=(
                    "Nu există donații înregistrate."
                ),
                color=discord.Color.dark_grey()
            )

            await message.edit(
                content=None,
                embed=embed,
                view=None
            )

            return

        embed = discord.Embed(
            title="🎁 PANOU DONAȚII",
            description=(
                "Mai jos sunt ultimele donații înregistrate."
            ),
            color=discord.Color.gold()
        )

        for donation in donations:

            if donation["status"] == "received":

                status = "✅ PRIMITĂ"

            else:

                status = "❌ NEPRIMITĂ"

            embed.add_field(
                name=(
                    f"🎁 Donația #{donation['id']} "
                    f"— {status}"
                ),
                value=(
                    f"👤 <@{donation['donor_id']}>\n"
                    f"📦 {donation['items'] or '-'}\n"
                    f"🔢 {donation['items_count'] or 0} obiecte"
                ),
                inline=False
            )

        await message.edit(
            content=None,
            embed=embed,
            view=None
        )

    except Exception as e:

        print(
            f"❌ Eroare panou donații: {e}"
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
        description=(
            "Nu există nicio patrulă activă."
        ),
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
# SETUP DONAȚII
# =========================================================

@bot.tree.command(
    name="setup_donatii",
    description="Creează panoul de donații în canalul curent."
)
@app_commands.check(has_donation_full_access)
async def setup_donatii(
    interaction: discord.Interaction
):

    embed = discord.Embed(
        title="🎁 PANOU DONAȚII",
        description=(
            "Nu există donații înregistrate."
        ),
        color=discord.Color.dark_grey()
    )

    message = await interaction.channel.send(
        embed=embed
    )

    set_setting(
        "donation_panel_channel_id",
        str(interaction.channel.id)
    )

    set_setting(
        "donation_panel_message_id",
        str(message.id)
    )

    await interaction.response.send_message(
        "✅ Panoul de donații a fost creat.",
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

    active_patrol = get_active_patrol()

    if active_patrol:

        await interaction.followup.send(
            "❌ Există deja o patrulă activă.\n\n"
            f"🚓 Patrula #{active_patrol['id']} este încă activă.\n"
            "Încheie patrula actuală înainte să începi una nouă.",
            ephemeral=True
        )

        return

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

    if nr_auto < 1:

        await interaction.followup.send(
            "❌ Numărul de mașini trebuie să fie cel puțin 1.",
            ephemeral=True
        )

        return

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

    image_url = None

    if poza is not None:

        image_url = await save_patrol_image(
            panel_channel,
            poza
        )

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

    await update_patrol_panel()

    mentions_text = " ".join(
        member.mention
        for member in members
    )

    await interaction.followup.send(
        "✅ **Patrula a fost începută cu succes!**\n\n"
        f"🚓 Patrula #{patrol_id}\n"
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

    cur.execute(
        "SELECT * FROM patrols WHERE id = ?",
        (patrol["id"],)
    )

    updated_patrol = cur.fetchone()

    conn.close()

    await update_patrol_panel()

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

        status = (
            "🟢 ACTIVĂ"
            if patrol["active"]
            else "🔴 ÎNCHEIATĂ"
        )

        embed.add_field(
            name=(
                f"🚓 Patrula #{patrol['id']} "
                f"— {status}"
            ),
            value=(
                f"📅 {patrol['patrol_date'] or '-'}\n"
                f"🕐 {patrol['patrol_time'] or '-'}\n"
                f"🚗 Auto: {patrol['cars_count'] or 0}\n"
                f"👤 Persoane: {patrol['people_count'] or 0}\n"
                ```python
f"🎨 {patrol['color'] or '-'}"
            ),
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# =========================================================
# PONTAJ
# =========================================================

@bot.tree.command(
    name="pontaj",
    description="Afișează persoanele pontate."
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
            "❌ Nu există pontaje în istoric.",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="📋 ISTORIC PONTAJ",
        color=discord.Color.blue()
    )

    for row in rows:

        embed.add_field(
            name=f"👤 {row['user_name'] or '-'}",
            value=(
                f"🟢 Început: {row['started_at'] or '-'}\n"
                f"🔴 Sfârșit: {row['ended_at'] or '-'}"
            ),
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# =========================================================
# DONAȚIE
# =========================================================

@bot.tree.command(
    name="donatie",
    description="Înregistrează o donație."
)
@app_commands.describe(
    obiecte="Obiectele donate, separate prin virgulă",
    numar="Numărul total de obiecte"
)
@app_commands.check(has_donation_create_access)
async def donatie(
    interaction: discord.Interaction,
    obiecte: str,
    numar: int
):

    if numar < 1:

        await interaction.response.send_message(
            "❌ Numărul de obiecte trebuie să fie cel puțin 1.",
            ephemeral=True
        )

        return

    panel_channel_id = get_setting(
        "donation_panel_channel_id"
    )

    if not panel_channel_id:

        await interaction.response.send_message(
            "❌ Panoul de donații nu este configurat.\n"
            "Un Lider, Co-Lider sau Discord Mod trebuie "
            "să ruleze mai întâi `/setup_donatii`.",
            ephemeral=True
        )

        return

    channel = bot.get_channel(
        int(panel_channel_id)
    )

    if channel is None:

        await interaction.response.send_message(
            "❌ Nu am găsit canalul de donații.",
            ephemeral=True
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO donations(
            donor_id,
            donor_name,
            items,
            items_count,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        interaction.user.id,
        interaction.user.display_name,
        obiecte,
        numar,
        "pending",
        now_string()
    ))

    donation_id = cur.lastrowid

    conn.commit()
    conn.close()

    donation = get_donation(
        donation_id
    )

    try:

        await channel.send(
            embed=create_donation_embed(
                donation
            ),
            view=DonationItemView(
                donation_id
            )
        )

    except Exception as e:

        print(
            f"❌ Eroare trimitere donație: {e}"
        )

        await interaction.response.send_message(
            "❌ Donația a fost salvată în baza de date, "
            "dar nu am putut trimite mesajul în canal.",
            ephemeral=True
        )

        return

    await update_donation_panel()

    await interaction.response.send_message(
        f"✅ Donația #{donation_id} a fost înregistrată cu succes.",
        ephemeral=True
    )


# =========================================================
# DONAȚII
# =========================================================

@bot.tree.command(
    name="donatii",
    description="Afișează ultimele donații."
)
@app_commands.check(has_donation_full_access)
async def donatii(
    interaction: discord.Interaction
):

    donations = get_donations()

    if not donations:

        await interaction.response.send_message(
            "❌ Nu există donații înregistrate.",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="🎁 ISTORIC DONAȚII",
        color=discord.Color.gold()
    )

    for donation in donations:

        if donation["status"] == "received":
            status = "✅ PRIMITĂ"
        else:
            status = "❌ NEPRIMITĂ"

        embed.add_field(
            name=(
                f"🎁 Donația #{donation['id']} "
                f"— {status}"
            ),
            value=(
                f"👤 <@{donation['donor_id']}>\n"
                f"📦 {donation['items'] or '-'}\n"
                f"🔢 {donation['items_count'] or 0} obiecte\n"
                f"📅 {donation['created_at'] or '-'}"
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

    print(
        f"✅ Bot conectat ca {bot.user}"
    )

    migrate_database()

    try:

        bot.add_view(
            PatrolView()
        )

        bot.add_view(
            AttendanceView()
        )

        for donation in get_donations():

            bot.add_view(
                DonationItemView(
                    donation["id"]
                )
            )

        print("✅ View-urile persistente au fost încărcate.")

    except Exception as e:

        print(
            f"❌ Eroare la încărcarea View-urilor: {e}"
        )

    try:

        synced = await bot.tree.sync()

        print(
            f"✅ Au fost sincronizate {len(synced)} comenzi slash."
        )

    except Exception as e:

        print(
            f"❌ Eroare sincronizare comenzi: {e}"
        )


# =========================================================
# ERORI COMENZI SLASH
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):

    if isinstance(
        error,
        app_commands.CheckFailure
    ):

        command_name = ""

        if interaction.command:
            command_name = interaction.command.name

        if command_name == "donatie":

            message = donation_create_access_message()

        else:

            message = donation_full_access_message()

        if interaction.response.is_done():

            await interaction.followup.sen


