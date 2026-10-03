import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv


# =========================
# CONFIGURARE
# =========================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Bucharest")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN lipsește din fișierul .env")

TZ = ZoneInfo(TIMEZONE_NAME)

DB_FILE = "pontaj.db"


# =========================
# DATABASE
# =========================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            display_name TEXT,
            avatar_url TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS breaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attendance_id INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER PRIMARY KEY,
            report_channel_id INTEGER
        )
    """)

    # Dacă baza de date era deja creată cu versiunea veche,
    # adăugăm coloanele noi fără să ștergem datele existente.
    columns = conn.execute("""
        PRAGMA table_info(attendance)
    """).fetchall()

    column_names = [column["name"] for column in columns]

    if "display_name" not in column_names:
        conn.execute("""
            ALTER TABLE attendance
            ADD COLUMN display_name TEXT
        """)

    if "avatar_url" not in column_names:
        conn.execute("""
            ALTER TABLE attendance
            ADD COLUMN avatar_url TEXT
        """)

    conn.commit()
    conn.close()


# =========================
# TIME
# =========================

def now_local():
    return datetime.now(TZ)


def time_string(dt):
    return dt.strftime("%H:%M:%S")


def date_string(dt):
    return dt.strftime("%Y-%m-%d")


def display_date(dt):
    return dt.strftime("%d.%m.%Y")


def parse_time(value):
    return datetime.fromisoformat(value)


def format_duration(seconds):
    seconds = max(0, int(seconds))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours}h {minutes}m {secs}s"


# =========================
# ATTENDANCE
# =========================

def get_today_attendance(guild_id, user_id):
    today = date_string(now_local())

    conn = get_db()

    row = conn.execute("""
        SELECT *
        FROM attendance
        WHERE guild_id = ?
        AND user_id = ?
        AND date = ?
        ORDER BY id DESC
        LIMIT 1
    """, (guild_id, user_id, today)).fetchone()

    conn.close()

    return row


def get_open_break(attendance_id):
    conn = get_db()

    row = conn.execute("""
        SELECT *
        FROM breaks
        WHERE attendance_id = ?
        AND end_time IS NULL
        ORDER BY id DESC
        LIMIT 1
    """, (attendance_id,)).fetchone()

    conn.close()

    return row


def calculate_break_seconds(attendance_id):
    conn = get_db()

    rows = conn.execute("""
        SELECT start_time, end_time
        FROM breaks
        WHERE attendance_id = ?
    """, (attendance_id,)).fetchall()

    conn.close()

    total = 0
    current = now_local()

    for row in rows:
        start = parse_time(row["start_time"])

        if row["end_time"]:
            end = parse_time(row["end_time"])
        else:
            end = current

        total += max(0, (end - start).total_seconds())

    return total


def calculate_worked_seconds(attendance):
    if not attendance["start_time"]:
        return 0

    start = parse_time(attendance["start_time"])

    if attendance["end_time"]:
        end = parse_time(attendance["end_time"])
    else:
        end = now_local()

    total = max(0, (end - start).total_seconds())

    total -= calculate_break_seconds(attendance["id"])

    return max(0, total)


# =========================
# ACTIONS
# =========================

def start_work(guild_id, user_id, display_name=None, avatar_url=None):
    existing = get_today_attendance(guild_id, user_id)

    if existing:
        if existing["end_time"]:
            return False, "Ai încheiat deja programul astăzi."

        return False, "Programul tău este deja început."

    now = now_local()

    conn = get_db()

    conn.execute("""
        INSERT INTO attendance
        (
            guild_id,
            user_id,
            date,
            start_time,
            display_name,
            avatar_url
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        guild_id,
        user_id,
        date_string(now),
        now.isoformat(),
        display_name,
        avatar_url
    ))

    conn.commit()
    conn.close()

    return True, f"Program început la **{time_string(now)}**."


def start_break(guild_id, user_id):
    attendance = get_today_attendance(guild_id, user_id)

    if not attendance:
        return False, "Nu ai început programul."

    if attendance["end_time"]:
        return False, "Programul tău este deja încheiat."

    if get_open_break(attendance["id"]):
        return False, "Ești deja în pauză."

    now = now_local()

    conn = get_db()

    conn.execute("""
        INSERT INTO breaks
        (attendance_id, start_time)
        VALUES (?, ?)
    """, (
        attendance["id"],
        now.isoformat()
    ))

    conn.commit()
    conn.close()

    return True, f"Pauză începută la **{time_string(now)}**."


def resume_work(guild_id, user_id):
    attendance = get_today_attendance(guild_id, user_id)

    if not attendance:
        return False, "Nu ai început programul."

    if attendance["end_time"]:
        return False, "Programul tău este deja încheiat."

    open_break = get_open_break(attendance["id"])

    if not open_break:
        return False, "Nu ești în pauză."

    now = now_local()

    conn = get_db()

    conn.execute("""
        UPDATE breaks
        SET end_time = ?
        WHERE id = ?
    """, (
        now.isoformat(),
        open_break["id"]
    ))

    conn.commit()
    conn.close()

    return True, f"Program reluat la **{time_string(now)}**."


def end_work(guild_id, user_id):
    attendance = get_today_attendance(guild_id, user_id)

    if not attendance:
        return False, "Nu ai început programul."

    if attendance["end_time"]:
        return False, "Programul tău este deja încheiat."

    now = now_local()

    open_break = get_open_break(attendance["id"])

    conn = get_db()

    if open_break:
        conn.execute("""
            UPDATE breaks
            SET end_time = ?
            WHERE id = ?
        """, (
            now.isoformat(),
            open_break["id"]
        ))

    conn.execute("""
        UPDATE attendance
        SET end_time = ?
        WHERE id = ?
    """, (
        now.isoformat(),
        attendance["id"]
    ))

    conn.commit()
    conn.close()

    attendance = get_today_attendance(guild_id, user_id)

    worked = calculate_worked_seconds(attendance)

    return True, (
        f"Program încheiat la **{time_string(now)}**.\n"
        f"Total lucrat: **{format_duration(worked)}**."
    )


# =========================
# BOT
# =========================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# PANEL
# =========================

class PresenceView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Începe programul",
        emoji="🟢",
        style=discord.ButtonStyle.success,
        custom_id="pontaj_start"
    )
    async def start_button(self, interaction, button):

        # Luăm automat numele și avatarul actual
        # direct de la utilizatorul care apasă butonul.
        display_name = interaction.user.display_name
        avatar_url = interaction.user.display_avatar.url

        success, message = start_work(
            interaction.guild.id,
            interaction.user.id,
            display_name,
            avatar_url
        )

        await interaction.response.send_message(
            message,
            ephemeral=True
        )

    @discord.ui.button(
        label="Începe pauza",
        emoji="☕",
        style=discord.ButtonStyle.primary,
        custom_id="pontaj_break"
    )
    async def break_button(self, interaction, button):

        success, message = start_break(
            interaction.guild.id,
            interaction.user.id
        )

        await interaction.response.send_message(
            message,
            ephemeral=True
        )

    @discord.ui.button(
        label="Reia programul",
        emoji="▶️",
        style=discord.ButtonStyle.primary,
        custom_id="pontaj_resume"
    )
    async def resume_button(self, interaction, button):

        success, message = resume_work(
            interaction.guild.id,
            interaction.user.id
        )

        await interaction.response.send_message(
            message,
            ephemeral=True
        )

    @discord.ui.button(
        label="Încheie programul",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        custom_id="pontaj_end"
    )
    async def end_button(self, interaction, button):

        success, message = end_work(
            interaction.guild.id,
            interaction.user.id
        )

        await interaction.response.send_message(
            message,
            ephemeral=True
        )


# =========================
# REPORT
# =========================

async def create_daily_report(guild):

    current = now_local()
    today = date_string(current)

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM attendance
        WHERE guild_id = ?
        AND date = ?
        ORDER BY start_time
    """, (
        guild.id,
        today
    )).fetchall()

    setting = conn.execute("""
        SELECT report_channel_id
        FROM settings
        WHERE guild_id = ?
    """, (
        guild.id,
    )).fetchone()

    conn.close()

    if not setting or not setting["report_channel_id"]:
        return

    channel = guild.get_channel(setting["report_channel_id"])

    if not channel:
        return

    # ==========================================
    # TOTALURI
    # ==========================================

    total_people = len(rows)
    total_worked_seconds = 0

    for row in rows:
        total_worked_seconds += calculate_worked_seconds(row)

    # ==========================================
    # EMBED PRINCIPAL
    # ==========================================

    embed = discord.Embed(
        title="📋 RAPORT PREZENȚĂ",
        description=(
            f"📅 Data: **{display_date(current)}**\n\n"
            f"👥 **Total persoane prezente: {total_people}**"
        ),
        color=discord.Color.green()
    )

    # ==========================================
    # DACĂ NU A FOST NIMENI
    # ==========================================

    if not rows:
        embed.description += (
            "\n\n❌ **Nu a fost înregistrată nicio prezență astăzi.**"
        )

        embed.set_footer(
            text="Raport automat de prezență"
        )

        await channel.send(embed=embed)
        return

    # Trimitem întâi antetul raportului
    await channel.send(embed=embed)

    # ==========================================
    # FIECARE PERSOANĂ
    # ==========================================

    for row in rows:

        # ==========================================
        # LUĂM DATELE SALVATE LA ÎNCEPUTUL PROGRAMULUI
        # ==========================================

        name = row["display_name"]
        avatar_url = row["avatar_url"]

        # ==========================================
        # DACĂ NU EXISTĂ DATE VECHI,
        # ÎNCERCĂM SĂ LE LUĂM DE LA DISCORD
        # ==========================================

        if not name or not avatar_url:

            member = guild.get_member(row["user_id"])

            if member is None:
                try:
                    member = await guild.fetch_member(row["user_id"])
                except discord.NotFound:
                    member = None
                except discord.HTTPException:
                    member = None

            if member:
                name = member.display_name
                avatar_url = member.display_avatar.url

                # Salvăm informația și în baza de date
                conn = get_db()

                conn.execute("""
                    UPDATE attendance
                    SET display_name = ?,
                        avatar_url = ?
                    WHERE id = ?
                """, (
                    name,
                    avatar_url,
                    row["id"]
                ))

                conn.commit()
                conn.close()

            else:
                # Ultima încercare: profilul global Discord
                try:
                    user = await bot.fetch_user(row["user_id"])

                    name = user.global_name or user.name
                    avatar_url = user.display_avatar.url

                except discord.NotFound:
                    name = name or "Utilizator necunoscut"

                except discord.HTTPException:
                    name = name or "Utilizator necunoscut"

        # ==========================================
        # ORE
        # ==========================================

        start = parse_time(row["start_time"])

        if row["end_time"]:
            end = parse_time(row["end_time"])
            end_text = time_string(end)
            status = "🔴 Program încheiat"
        else:
            end_text = "încă activ"
            status = "🟢 Program activ"

        break_seconds = calculate_break_seconds(row["id"])
        worked_seconds = calculate_worked_seconds(row)

        # ==========================================
        # EMBED PERSOANĂ
        # ==========================================

        person_embed = discord.Embed(
            color=discord.Color.green()
        )

        if avatar_url:
            person_embed.set_author(
                name=name,
                icon_url=avatar_url
            )

            person_embed.set_thumbnail(
                url=avatar_url
            )
        else:
            person_embed.set_author(
                name=name
            )

        person_embed.description = (
            f"{status}\n\n"
            f"🟢 **Început:** `{time_string(start)}`\n"
            f"🔴 **Sfârșit:** `{end_text}`\n"
            f"☕ **Pauză:** `{format_duration(break_seconds)}`\n"
            f"⏱️ **Lucrat:** `{format_duration(worked_seconds)}`"
        )

        await channel.send(
            embed=person_embed
        )

    # ==========================================
    # TOTAL FINAL
    # ==========================================

    total_embed = discord.Embed(
        title="📊 TOTAL ZILNIC",
        description=(
            f"📅 **{display_date(current)}**\n\n"
            f"👥 **Total persoane prezente:** {total_people}\n"
            f"⏱️ **Total ore lucrate:** "
            f"{format_duration(total_worked_seconds)}"
        ),
        color=discord.Color.blue()
    )

    total_embed.set_footer(
        text="Raport automat de prezență"
    )

    await channel.send(
        embed=total_embed
    )


# =========================
# COMMANDS
# =========================

@bot.tree.command(
    name="setup_prezenta",
    description="Creează panoul de pontaj"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_prezenta(interaction: discord.Interaction):

    conn = get_db()

    conn.execute("""
        INSERT INTO settings (guild_id, report_channel_id)
        VALUES (?, ?)
        ON CONFLICT(guild_id)
        DO UPDATE SET report_channel_id = excluded.report_channel_id
    """, (
        interaction.guild.id,
        interaction.channel.id
    ))

    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="🕐 Pontaj / Prezență",
        description=(
            "Folosește butoanele de mai jos pentru a înregistra "
            "programul și pauzele."
        ),
        color=discord.Color.blue()
    )

    embed.add_field(
        name="🟢 Începe programul",
        value="Înregistrează începutul programului.",
        inline=False
    )

    embed.add_field(
        name="☕ Începe pauza",
        value="Începe o pauză. Pauza nu se calculează ca timp lucrat.",
        inline=False
    )

    embed.add_field(
        name="▶️ Reia programul",
        value="Încheie pauza și reia programul.",
        inline=False
    )

    embed.add_field(
        name="🔴 Încheie programul",
        value="Înregistrează sfârșitul programului.",
        inline=False
    )

    await interaction.response.send_message(
        embed=embed,
        view=PresenceView()
    )


@bot.tree.command(
    name="prezenta",
    description="Vezi situația ta de astăzi"
)
async def prezenta(interaction: discord.Interaction):

    attendance = get_today_attendance(
        interaction.guild.id,
        interaction.user.id
    )

    if not attendance:
        await interaction.response.send_message(
            "Nu ai nicio înregistrare astăzi.",
            ephemeral=True
        )
        return

    start = parse_time(attendance["start_time"])

    if attendance["end_time"]:
        end = parse_time(attendance["end_time"])
        end_text = time_string(end)
    else:
        end_text = "încă activ"

    break_seconds = calculate_break_seconds(attendance["id"])
    worked_seconds = calculate_worked_seconds(attendance)

    message = (
        "📋 **Prezența ta de astăzi**\n\n"
        f"🟢 Start: **{time_string(start)}**\n"
        f"🔴 Final: **{end_text}**\n"
        f"☕ Pauză: **{format_duration(break_seconds)}**\n"
        f"⏱️ Lucrat: **{format_duration(worked_seconds)}**"
    )

    await interaction.response.send_message(
        message,
        ephemeral=True
    )


@bot.tree.command(
    name="raport",
    description="Trimite raportul de astăzi"
)
@app_commands.checks.has_permissions(administrator=True)
async def raport(interaction: discord.Interaction):

    await interaction.response.defer(ephemeral=True)

    await create_daily_report(interaction.guild)

    await interaction.followup.send(
        "📋 Raportul a fost trimis.",
        ephemeral=True
    )


# =========================
# DAILY REPORT
# =========================

@tasks.loop(minutes=1)
async def daily_report_task():

    current = now_local()

    if current.hour != 23 or current.minute != 59:
        return

    for guild in bot.guilds:
        try:
            await create_daily_report(guild)
        except Exception as e:
            print(
                f"Eroare la raportul pentru {guild.name}: {e}"
            )


# =========================
# READY
# =========================

@bot.event
async def on_ready():

    init_db()

    bot.add_view(PresenceView())

    try:
        synced = await bot.tree.sync()
        print(f"Comenzi sincronizate: {len(synced)}")
    except Exception as e:
        print(f"Eroare sincronizare comenzi: {e}")

    if not daily_report_task.is_running():
        daily_report_task.start()

    print(f"Bot conectat ca {bot.user}")
    print(f"Timezone: {TIMEZONE_NAME}")


# =========================
# START
# =========================

init_db()

bot.run(TOKEN)