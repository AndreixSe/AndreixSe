import os
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv


# =========================================================
# CONFIG
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

# Railway Volume -> /data
# Local -> folderul proiectului
if os.path.isdir("/data"):
    DB_FILE = "/data/pontaj.db"
else:
    DB_FILE = "pontaj.db"


# =========================================================
# DISCORD
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
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            display_name TEXT,
            avatar_url TEXT,
            work_start TEXT,
            work_end TEXT,
            total_break_seconds INTEGER DEFAULT 0,
            current_break_start TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER PRIMARY KEY,
            report_channel_id INTEGER
        )
    """)

    # Compatibilitate cu o bază de date mai veche
    columns = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(attendance)").fetchall()
    }

    if "display_name" not in columns:
        cur.execute(
            "ALTER TABLE attendance ADD COLUMN display_name TEXT"
        )

    if "avatar_url" not in columns:
        cur.execute(
            "ALTER TABLE attendance ADD COLUMN avatar_url TEXT"
        )

    if "current_break_start" not in columns:
        cur.execute(
            "ALTER TABLE attendance ADD COLUMN current_break_start TEXT"
        )

    conn.commit()
    conn.close()


# =========================================================
# TIME HELPERS
# =========================================================

def now_local():
    return datetime.now(TZ)


def dt_to_str(dt):
    return dt.astimezone(timezone.utc).isoformat()


def str_to_dt(value):
    if not value:
        return None

    return datetime.fromisoformat(value)


def format_duration(seconds):
    seconds = max(0, int(seconds))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours:
        return f"{hours}h {minutes}m {secs}s"

    if minutes:
        return f"{minutes}m {secs}s"

    return f"{secs}s"


# =========================================================
# USER / ATTENDANCE HELPERS
# =========================================================

def get_active_attendance(guild_id, user_id):
    conn = get_db()

    row = conn.execute("""
        SELECT *
        FROM attendance
        WHERE guild_id = ?
          AND user_id = ?
          AND work_end IS NULL
        ORDER BY id DESC
        LIMIT 1
    """, (guild_id, user_id)).fetchone()

    conn.close()
    return row


def get_today_records(guild_id):
    today = now_local().date()

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM attendance
        WHERE guild_id = ?
        ORDER BY id ASC
    """, (guild_id,)).fetchall()

    conn.close()

    result = []

    for row in rows:
        created = row["created_at"]

        try:
            created_dt = str_to_dt(created).astimezone(TZ)
        except Exception:
            continue

        if created_dt.date() == today:
            result.append(row)

    return result


def save_user_info(guild, user):
    display_name = getattr(user, "display_name", user.name)

    avatar_url = None

    try:
        if user.display_avatar:
            avatar_url = str(user.display_avatar.url)
    except Exception:
        pass

    return display_name, avatar_url


# =========================================================
# STATUS ACTIONS
# =========================================================

def start_work(guild, user):
    existing = get_active_attendance(guild.id, user.id)

    if existing:
        return False, "Ești deja în program."

    display_name, avatar_url = save_user_info(guild, user)

    now = now_local()

    conn = get_db()

    conn.execute("""
        INSERT INTO attendance (
            user_id,
            guild_id,
            display_name,
            avatar_url,
            work_start,
            work_end,
            total_break_seconds,
            current_break_start,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, NULL, 0, NULL, ?)
    """, (
        user.id,
        guild.id,
        display_name,
        avatar_url,
        dt_to_str(now),
        dt_to_str(now),
    ))

    conn.commit()
    conn.close()

    return True, f"Program început la **{now.strftime('%H:%M:%S')}**."


def start_break(guild, user):
    row = get_active_attendance(guild.id, user.id)

    if not row:
        return False, "Nu ești în program."

    if row["current_break_start"]:
        return False, "Ești deja în pauză."

    now = now_local()

    conn = get_db()

    conn.execute("""
        UPDATE attendance
        SET current_break_start = ?
        WHERE id = ?
    """, (
        dt_to_str(now),
        row["id"],
    ))

    conn.commit()
    conn.close()

    return True, f"Pauză începută la **{now.strftime('%H:%M:%S')}**."


def resume_work(guild, user):
    row = get_active_attendance(guild.id, user.id)

    if not row:
        return False, "Nu ești în program."

    if not row["current_break_start"]:
        return False, "Nu ești în pauză."

    now = now_local()
    break_start = str_to_dt(row["current_break_start"])

    break_seconds = int(
        (now.astimezone(timezone.utc)
         - break_start.astimezone(timezone.utc)).total_seconds()
    )

    total_break = (row["total_break_seconds"] or 0) + break_seconds

    conn = get_db()

    conn.execute("""
        UPDATE attendance
        SET total_break_seconds = ?,
            current_break_start = NULL
        WHERE id = ?
    """, (
        total_break,
        row["id"],
    ))

    conn.commit()
    conn.close()

    return True, (
        f"Ai revenit din pauză. "
        f"Pauza a durat **{format_duration(break_seconds)}**."
    )


def end_work(guild, user):
    row = get_active_attendance(guild.id, user.id)

    if not row:
        return False, "Nu ești în program."

    if row["current_break_start"]:
        return False, "Ești în pauză. Apasă mai întâi **▶️ Reia programul**."

    now = now_local()

    work_start = str_to_dt(row["work_start"])

    total_elapsed = int(
        (
            now.astimezone(timezone.utc)
            - work_start.astimezone(timezone.utc)
        ).total_seconds()
    )

    worked_seconds = max(
        0,
        total_elapsed - (row["total_break_seconds"] or 0)
    )

    conn = get_db()

    conn.execute("""
        UPDATE attendance
        SET work_end = ?
        WHERE id = ?
    """, (
        dt_to_str(now),
        row["id"],
    ))

    conn.commit()
    conn.close()

    return True, (
        f"Program încheiat la **{now.strftime('%H:%M:%S')}**.\n"
        f"Timp lucrat: **{format_duration(worked_seconds)}**."
    )


# =========================================================
# REPORT CHANNEL
# =========================================================

def set_report_channel(guild_id, channel_id):
    conn = get_db()

    conn.execute("""
        INSERT INTO settings (guild_id, report_channel_id)
        VALUES (?, ?)
        ON CONFLICT(guild_id)
        DO UPDATE SET report_channel_id = excluded.report_channel_id
    """, (
        guild_id,
        channel_id,
    ))

    conn.commit()
    conn.close()


def get_report_channel_id(guild_id):
    conn = get_db()

    row = conn.execute("""
        SELECT report_channel_id
        FROM settings
        WHERE guild_id = ?
    """, (guild_id,)).fetchone()

    conn.close()

    if not row:
        return None

    return row["report_channel_id"]


# =========================================================
# REPORT
# =========================================================

async def send_daily_report(guild):
    records = get_today_records(guild.id)

    if not records:
        return

    channel_id = get_report_channel_id(guild.id)

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if channel is None:
        try:
            channel = await guild.fetch_channel(channel_id)
        except Exception:
            return

    if not isinstance(channel, discord.TextChannel):
        return

    # Main embed
    report_embed = discord.Embed(
        title="📋 Raport pontaj",
        description=(
            f"Raport pentru **{now_local().strftime('%d.%m.%Y')}**"
        ),
        color=discord.Color.blue(),
        timestamp=now_local(),
    )

    total_worked = 0
    total_people = 0

    for row in records:
        start = str_to_dt(row["work_start"])
        end = str_to_dt(row["work_end"])

        if not start:
            continue

        if end:
            end_dt = end
        else:
            end_dt = now_local()

        elapsed = int(
            (
                end_dt.astimezone(timezone.utc)
                - start.astimezone(timezone.utc)
            ).total_seconds()
        )

        # Dacă persoana este încă în pauză la momentul raportului,
        # calculăm și pauza curentă.
        total_break = row["total_break_seconds"] or 0

        if row["current_break_start"]:
            current_break = str_to_dt(row["current_break_start"])

            if current_break:
                total_break += int(
                    (
                        end_dt.astimezone(timezone.utc)
                        - current_break.astimezone(timezone.utc)
                    ).total_seconds()
                )

        worked = max(0, elapsed - total_break)

        total_worked += worked
        total_people += 1

        name = row["display_name"] or f"User {row['user_id']}"

        report_embed.add_field(
            name=name,
            value=f"⏱️ {format_duration(worked)}",
            inline=False,
        )

    report_embed.add_field(
        name="👥 Persoane",
        value=str(total_people),
        inline=True,
    )

    report_embed.add_field(
        name="⏱️ Total lucrat",
        value=format_duration(total_worked),
        inline=True,
    )

    await channel.send(embed=report_embed)

    # Detalii individuale
    for row in records:
        start = str_to_dt(row["work_start"])

        if not start:
            continue

        end = str_to_dt(row["work_end"])
        end_dt = end if end else now_local()

        elapsed = int(
            (
                end_dt.astimezone(timezone.utc)
                - start.astimezone(timezone.utc)
            ).total_seconds()
        )

        total_break = row["total_break_seconds"] or 0

        if row["current_break_start"]:
            current_break = str_to_dt(row["current_break_start"])

            if current_break:
                total_break += int(
                    (
                        end_dt.astimezone(timezone.utc)
                        - current_break.astimezone(timezone.utc)
                    ).total_seconds()
                )

        worked = max(0, elapsed - total_break)

        name = row["display_name"] or f"User {row['user_id']}"

        avatar_url = row["avatar_url"]

        # Încercăm să actualizăm informațiile din Discord
        member = guild.get_member(row["user_id"])

        if member:
            name = member.display_name

            try:
                avatar_url = str(member.display_avatar.url)
            except Exception:
                pass

        if not member:
            try:
                member = await guild.fetch_member(row["user_id"])

                name = member.display_name

                try:
                    avatar_url = str(member.display_avatar.url)
                except Exception:
                    pass

            except Exception:
                pass

        if not member:
            try:
                user = await bot.fetch_user(row["user_id"])

                name = getattr(user, "display_name", user.name)

                try:
                    avatar_url = str(user.display_avatar.url)
                except Exception:
                    pass

            except Exception:
                pass

        embed = discord.Embed(
            title=f"👤 {name}",
            color=discord.Color.green(),
        )

        embed.add_field(
            name="🟢 Început",
            value=start.astimezone(TZ).strftime("%H:%M:%S"),
            inline=True,
        )

        embed.add_field(
            name="🔴 Sfârșit",
            value=(
                end.astimezone(TZ).strftime("%H:%M:%S")
                if end
                else "Încă activ"
            ),
            inline=True,
        )

        embed.add_field(
            name="☕ Pauză",
            value=format_duration(total_break),
            inline=True,
        )

        embed.add_field(
            name="⏱️ Timp lucrat",
            value=format_duration(worked),
            inline=False,
        )

        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        await channel.send(embed=embed)

    # Total final
    total_embed = discord.Embed(
        title="📊 TOTAL",
        description=(
            f"**{total_people}** persoane\n"
            f"**{format_duration(total_worked)}** timp lucrat total"
        ),
        color=discord.Color.gold(),
    )

    await channel.send(embed=total_embed)


# =========================================================
# AUTOMATIC REPORT
# =========================================================

@tasks.loop(minutes=1)
async def automatic_report():
    current = now_local()

    if current.hour != 23 or current.minute != 59:
        return

    for guild in bot.guilds:
        try:
            await send_daily_report(guild)
        except Exception as e:
            print(
                f"Eroare raport automat pentru {guild.name}: {e}"
            )


@automatic_report.before_loop
async def before_automatic_report():
    await bot.wait_until_ready()


# =========================================================
# BUTTON VIEW
# =========================================================

class PresenceView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Începe programul",
        style=discord.ButtonStyle.success,
        emoji="🟢",
        custom_id="presence:start",
    )
    async def start_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not interaction.guild:
            return

        success, message = start_work(
            interaction.guild,
            interaction.user,
        )

        if success:
            await interaction.response.send_message(
                f"🟢 {message}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"⚠️ {message}",
                ephemeral=True,
            )

    @discord.ui.button(
        label="Începe pauza",
        style=discord.ButtonStyle.primary,
        emoji="☕",
        custom_id="presence:break",
    )
    async def break_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not interaction.guild:
            return

        success, message = start_break(
            interaction.guild,
            interaction.user,
        )

        if success:
            await interaction.response.send_message(
                f"☕ {message}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"⚠️ {message}",
                ephemeral=True,
            )

    @discord.ui.button(
        label="Reia programul",
        style=discord.ButtonStyle.secondary,
        emoji="▶️",
        custom_id="presence:resume",
    )
    async def resume_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not interaction.guild:
            return

        success, message = resume_work(
            interaction.guild,
            interaction.user,
        )

        if success:
            await interaction.response.send_message(
                f"▶️ {message}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"⚠️ {message}",
                ephemeral=True,
            )

    @discord.ui.button(
        label="Încheie programul",
        style=discord.ButtonStyle.danger,
        emoji="🔴",
        custom_id="presence:end",
    )
    async def end_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not interaction.guild:
            return

        success, message = end_work(
            interaction.guild,
            interaction.user,
        )

        if success:
            await interaction.response.send_message(
                f"🔴 {message}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"⚠️ {message}",
                ephemeral=True,
            )


# =========================================================
# SLASH COMMANDS
# =========================================================

@bot.tree.command(
    name="setup_prezenta",
    description="Configurează panoul de pontaj în acest canal."
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_prezenta(interaction: discord.Interaction):

    if not interaction.guild:
        await interaction.response.send_message(
            "Comanda poate fi folosită doar pe un server.",
            ephemeral=True,
        )
        return

    set_report_channel(
        interaction.guild.id,
        interaction.channel.id,
    )

    embed = discord.Embed(
        title="📋 Pontaj",
        description=(
            "Folosește butoanele de mai jos pentru pontaj.\n\n"
            "🟢 **Începe programul** — începi programul\n"
            "☕ **Începe pauza** — începi o pauză\n"
            "▶️ **Reia programul** — revii din pauză\n"
            "🔴 **Încheie programul** — termini programul\n\n"
            "Pauzele sunt scăzute din timpul total lucrat."
        ),
        color=discord.Color.blurple(),
    )

    await interaction.channel.send(
        embed=embed,
        view=PresenceView(),
    )

    await interaction.response.send_message(
        "✅ Panoul de pontaj a fost configurat.",
        ephemeral=True,
    )


@bot.tree.command(
    name="prezenta",
    description="Vezi statusul tău actual."
)
async def prezenta(interaction: discord.Interaction):

    if not interaction.guild:
        await interaction.response.send_message(
            "Comanda poate fi folosită doar pe un server.",
            ephemeral=True,
        )
        return

    row = get_active_attendance(
        interaction.guild.id,
        interaction.user.id,
    )

    if not row:
        await interaction.response.send_message(
            "⚪ Nu ești în program.",
            ephemeral=True,
        )
        return

    start = str_to_dt(row["work_start"])

    if row["current_break_start"]:
        status = "☕ Ești în pauză."

        break_start = str_to_dt(row["current_break_start"])

        break_duration = int(
            (
                now_local().astimezone(timezone.utc)
                - break_start.astimezone(timezone.utc)
            ).total_seconds()
        )

        extra = (
            f"\nPauza curentă: "
            f"**{format_duration(break_duration)}**"
        )
    else:
        status = "🟢 Ești în program."
        extra = ""

    await interaction.response.send_message(
        f"{status}\n"
        f"Început: **{start.astimezone(TZ).strftime('%H:%M:%S')}**"
        f"{extra}",
        ephemeral=True,
    )


@bot.tree.command(
    name="raport",
    description="Trimite raportul de pontaj pentru azi."
)
@app_commands.checks.has_permissions(administrator=True)
async def raport(interaction: discord.Interaction):

    if not interaction.guild:
        await interaction.response.send_message(
            "Comanda poate fi folosită doar pe un server.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    await send_daily_report(interaction.guild)

    await interaction.followup.send(
        "✅ Raportul a fost trimis.",
        ephemeral=True,
    )


# =========================================================
# ERROR HANDLING
# =========================================================

@setup_prezenta.error
async def setup_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(
        error,
        app_commands.errors.MissingPermissions,
    ):
        await interaction.response.send_message(
            "❌ Ai nevoie de permisiunea Administrator.",
            ephemeral=True,
        )


@raport.error
async def raport_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(
        error,
        app_commands.errors.MissingPermissions,
    ):
        await interaction.response.send_message(
            "❌ Ai nevoie de permisiunea Administrator.",
            ephemeral=True,
        )


# =========================================================
# BOT EVENTS
# =========================================================

@bot.event
async def on_ready():

    print(f"Bot conectat ca {bot.user}")
    print(f"Timezone: {TIMEZONE_NAME}")
    print(f"Database: {DB_FILE}")

    if not getattr(bot, "_presence_view_added", False):
        bot.add_view(PresenceView())
        bot._presence_view_added = True

    if not automatic_report.is_running():
        automatic_report.start()

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