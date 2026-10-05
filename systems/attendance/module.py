import discord
from datetime import datetime
from zoneinfo import ZoneInfo

from core.bot import bot
from core.database import get_db, now_string


# =========================================================
# ATTENDANCE ROLE ACCESS
# =========================================================

ROLE_DISCORD_MOD = 1554072182735511623
ROLE_LIDER = 1528799552075989102
ROLE_CO_LIDER = 1527919721629089862
ROLE_MIEMBRO = 1528804522938597557

ATTENDANCE_ADMIN_ROLES = {
    ROLE_DISCORD_MOD,
    ROLE_LIDER,
    ROLE_CO_LIDER,
}

ATTENDANCE_MEMBER_ROLES = ATTENDANCE_ADMIN_ROLES | {
    ROLE_MIEMBRO,
}


def has_any_role(member, allowed_role_ids):
    return any(
        role.id in allowed_role_ids
        for role in getattr(member, "roles", [])
    )


def is_attendance_admin(member):
    return has_any_role(member, ATTENDANCE_ADMIN_ROLES)


def can_use_attendance(member):
    return has_any_role(member, ATTENDANCE_MEMBER_ROLES)


# =========================================================
# HELPERS
# =========================================================

def romania_now():
    return datetime.now(ZoneInfo("Europe/Bucharest"))


def today_string():
    return romania_now().strftime("%d.%m.%Y")


def time_only(value):
    if not value:
        return "-"
    value = str(value)
    try:
        return datetime.strptime(value, "%d.%m.%Y %H:%M:%S").strftime("%H:%M:%S")
    except ValueError:
        try:
            return datetime.fromisoformat(value).strftime("%H:%M:%S")
        except ValueError:
            return value


def duration_text(started_at, ended_at=None):
    if not started_at:
        return "-"

    def parse(value):
        if not value:
            return romania_now().replace(tzinfo=None)
        value = str(value)
        try:
            return datetime.strptime(value, "%d.%m.%Y %H:%M:%S")
        except ValueError:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None

    start = parse(started_at)
    end = parse(ended_at)

    if not start or not end:
        return "-"

    seconds = max(0, int((end - start).total_seconds()))
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)

    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def get_day(day_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM attendance_days WHERE id = ?", (day_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_latest_today_day():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT *
        FROM attendance_days
        WHERE attendance_date = ?
        ORDER BY id DESC
        LIMIT 1
    """, (today_string(),))
    row = cur.fetchone()
    conn.close()
    return row


def get_latest_open_day():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT *
        FROM attendance_days
        WHERE status = 'open'
        ORDER BY id DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    return row


def get_entries(day_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT *
        FROM attendance_daily_entries
        WHERE day_id = ?
        ORDER BY started_at ASC, id ASC
    """, (day_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def create_daily_embed(day_id):
    day = get_day(day_id)

    if not day:
        return discord.Embed(
            title="🕐 PONTAJ ZILNIC",
            description="❌ Pontajul nu mai există.",
            color=discord.Color.red()
        )

    entries = get_entries(day_id)
    active = [row for row in entries if not row["ended_at"]]
    finished = [row for row in entries if row["ended_at"]]

    is_open = day["status"] == "open"

    embed = discord.Embed(
        title="🕐 PONTAJ ZILNIC",
        description=(
            f"📅 **Data:** {day['attendance_date']}\n"
            f"{'🟢 **Status:** DESCHIS' if is_open else '🔒 **Status:** ÎNCHEIAT'}"
        ),
        color=discord.Color.green() if is_open else discord.Color.red()
    )

    embed.add_field(
        name="📊 Situație",
        value=(
            f"👥 Participanți: **{len(entries)}**\n"
            f"🟢 Încă pontați: **{len(active)}**\n"
            f"✅ Au încheiat: **{len(finished)}**"
        ),
        inline=False
    )

    if entries:
        lines = []
        for row in entries:
            if row["ended_at"]:
                lines.append(
                    f"👤 <@{row['user_id']}> • "
                    f"`{time_only(row['started_at'])}` → "
                    f"`{time_only(row['ended_at'])}`"
                )
            else:
                lines.append(
                    f"👤 <@{row['user_id']}> • "
                    f"🟢 de la `{time_only(row['started_at'])}`"
                )

        text = "\n".join(lines)
        if len(text) > 3800:
            text = text[:3750] + "\n…"

        embed.add_field(
            name="👥 Pontajul zilei",
            value=text,
            inline=False
        )
    else:
        embed.add_field(
            name="👥 Pontajul zilei",
            value="Nu s-a pontat nimeni încă.",
            inline=False
        )

    if not is_open:
        embed.add_field(
            name="🔴 Închis la",
            value=f"`{time_only(day['closed_at'])}`",
            inline=False
        )

    embed.set_footer(
        text="Pontaj zilnic • fiecare panou rămâne ca evidență"
    )

    return embed


def create_history_embed(day_id):
    day = get_day(day_id)
    entries = get_entries(day_id)

    embed = discord.Embed(
        title="📋 ISTORIC PONTAJ — ZILNIC",
        description=(
            f"📅 **Data:** {day['attendance_date']}\n"
            "Sunt afișate doar înregistrările acestui pontaj."
        ),
        color=discord.Color.blue()
    )

    if not entries:
        embed.add_field(
            name="ℹ️ Istoric",
            value="Nu există înregistrări pentru această zi.",
            inline=False
        )
        return embed

    for row in entries[:25]:
        if row["ended_at"]:
            status = (
                f"🟢 Intrare: `{time_only(row['started_at'])}`\n"
                f"🔴 Ieșire: `{time_only(row['ended_at'])}`\n"
                f"⏱️ Durată: **{duration_text(row['started_at'], row['ended_at'])}**"
            )
        else:
            status = (
                f"🟢 Intrare: `{time_only(row['started_at'])}`\n"
                f"🟡 Ieșire: **Încă pontat**\n"
                f"⏱️ Durată curentă: **{duration_text(row['started_at'])}**"
            )

        display_name = row["user_name"] or f"<@{row['user_id']}>"
        embed.add_field(
            name=f"👤 {display_name}",
            value=status,
            inline=False
        )

    if len(entries) > 25:
        embed.set_footer(
            text=f"Sunt afișate primele 25 din {len(entries)} înregistrări."
        )

    return embed


# =========================================================
# VIEW
# =========================================================

class AttendanceView(discord.ui.View):
    def __init__(self, day_id=None):
        super().__init__(timeout=None)
        self.day_id = day_id

    async def resolve_day(self, interaction):
        if self.day_id:
            return get_day(self.day_id)

        # Compatibilitate cu view-ul persistent înregistrat la pornirea botului.
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT *
            FROM attendance_days
            WHERE message_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (interaction.message.id,))
        day = cur.fetchone()
        conn.close()
        return day

    @discord.ui.button(
        label="Începe pontaj",
        style=discord.ButtonStyle.success,
        emoji="🟢",
        custom_id="attendance_start"
    )
    async def start_attendance(self, interaction, button):
        await interaction.response.defer(ephemeral=True)

        if not can_use_attendance(interaction.user):
            await interaction.followup.send(
                "❌ Nu ai rolul necesar pentru a folosi pontajul.",
                ephemeral=True
            )
            return

        day = await self.resolve_day(interaction)

        if not day:
            await interaction.followup.send(
                "❌ Acest panou nu mai este asociat unui pontaj.",
                ephemeral=True
            )
            return

        if day["status"] != "open":
            await interaction.followup.send(
                "🔒 Pontajul acestei zile este încheiat. Nu te mai poți ponta aici.",
                ephemeral=True
            )
            return

        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT *
                FROM attendance_daily_entries
                WHERE day_id = ? AND user_id = ?
                LIMIT 1
            """, (day["id"], interaction.user.id))

            if cur.fetchone():
                await interaction.followup.send(
                    "❌ Ai fost deja pontat în acest pontaj zilnic.",
                    ephemeral=True
                )
                return

            cur.execute("""
                INSERT INTO attendance_daily_entries(
                    day_id, user_id, user_name, started_at, ended_at
                )
                VALUES (?, ?, ?, ?, NULL)
            """, (
                day["id"],
                interaction.user.id,
                interaction.user.display_name,
                now_string()
            ))
            conn.commit()

        except Exception as error:
            conn.rollback()
            print(f"❌ Eroare pornire pontaj zilnic: {error}")
            await interaction.followup.send(
                "❌ A apărut o eroare la pornirea pontajului.",
                ephemeral=True
            )
            return
        finally:
            conn.close()

        await update_daily_panel(day["id"])
        await interaction.followup.send(
            "✅ Ai început pontajul.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Încheie pontaj",
        style=discord.ButtonStyle.danger,
        emoji="🔴",
        custom_id="attendance_stop"
    )
    async def stop_attendance(self, interaction, button):
        await interaction.response.defer(ephemeral=True)

        if not can_use_attendance(interaction.user):
            await interaction.followup.send(
                "❌ Nu ai rolul necesar pentru a folosi pontajul.",
                ephemeral=True
            )
            return

        day = await self.resolve_day(interaction)

        if not day:
            await interaction.followup.send(
                "❌ Acest panou nu mai este asociat unui pontaj.",
                ephemeral=True
            )
            return

        if day["status"] != "open":
            await interaction.followup.send(
                "🔒 Pontajul acestei zile este deja încheiat.",
                ephemeral=True
            )
            return

        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT *
                FROM attendance_daily_entries
                WHERE day_id = ? AND user_id = ?
                LIMIT 1
            """, (day["id"], interaction.user.id))
            entry = cur.fetchone()

            if not entry:
                await interaction.followup.send(
                    "❌ Nu ești pontat în acest pontaj.",
                    ephemeral=True
                )
                return

            if entry["ended_at"]:
                await interaction.followup.send(
                    "❌ Ai încheiat deja pontajul.",
                    ephemeral=True
                )
                return

            cur.execute("""
                UPDATE attendance_daily_entries
                SET ended_at = ?
                WHERE id = ?
            """, (now_string(), entry["id"]))
            conn.commit()

        except Exception as error:
            conn.rollback()
            print(f"❌ Eroare încheiere pontaj membru: {error}")
            await interaction.followup.send(
                "❌ A apărut o eroare la încheierea pontajului.",
                ephemeral=True
            )
            return
        finally:
            conn.close()

        await update_daily_panel(day["id"])
        await interaction.followup.send(
            "✅ Ai încheiat pontajul.",
            ephemeral=True
        )


async def update_daily_panel(day_id):
    day = get_day(day_id)
    if not day or not day["channel_id"] or not day["message_id"]:
        return

    try:
        channel = bot.get_channel(int(day["channel_id"]))
        if channel is None:
            channel = await bot.fetch_channel(int(day["channel_id"]))

        message = await channel.fetch_message(int(day["message_id"]))
        await message.edit(
            embed=create_daily_embed(day_id),
            view=AttendanceView(day_id)
        )
    except Exception as error:
        print(f"❌ Eroare actualizare panou zilnic {day_id}: {error}")


# =========================================================
# COMMANDS
# =========================================================

@bot.tree.command(
    name="setup_pontaj",
    description="Creează un pontaj nou pentru ziua curentă."
)
async def setup_pontaj(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not is_attendance_admin(interaction.user):
        await interaction.followup.send(
            "❌ Doar Lider, Co-Lider sau Discord Mod poate crea pontajul.",
            ephemeral=True
        )
        return

    conn = get_db()
    cur = conn.cursor()

    try:
        # Cerință: setup-ul poate fi rulat zilnic și nu este blocat de
        # pontajele/panourile anterioare. Fiecare rulare creează o sesiune nouă.
        cur.execute("""
            INSERT INTO attendance_days(
                attendance_date,
                status,
                created_at,
                channel_id
            )
            VALUES (?, 'open', ?, ?)
        """, (
            today_string(),
            now_string(),
            interaction.channel.id
        ))
        day_id = cur.lastrowid
        conn.commit()

        message = await interaction.channel.send(
            embed=create_daily_embed(day_id),
            view=AttendanceView(day_id)
        )

        cur.execute("""
            UPDATE attendance_days
            SET message_id = ?
            WHERE id = ?
        """, (message.id, day_id))
        conn.commit()

    except Exception as error:
        conn.rollback()
        print(f"❌ Eroare setup pontaj zilnic: {error}")
        await interaction.followup.send(
            "❌ Panoul de pontaj nu a putut fi creat.",
            ephemeral=True
        )
        return
    finally:
        conn.close()

    await interaction.followup.send(
        f"✅ Pontajul pentru **{today_string()}** a fost creat.",
        ephemeral=True
    )


@bot.tree.command(
    name="incheie_pontaj",
    description="Închide pontajul zilnic curent fără să șteargă evidența."
)
async def incheie_pontaj(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not is_attendance_admin(interaction.user):
        await interaction.followup.send(
            "❌ Doar Lider, Co-Lider sau Discord Mod poate închide pontajul.",
            ephemeral=True
        )
        return

    day = get_latest_open_day()

    if not day:
        await interaction.followup.send(
            "❌ Nu există niciun pontaj deschis.",
            ephemeral=True
        )
        return

    conn = get_db()
    cur = conn.cursor()

    try:
        closed_at = now_string()

        # Persoanele care încă sunt pontate sunt închise automat la ora
        # închiderii generale, astfel istoricul rămâne complet.
        cur.execute("""
            UPDATE attendance_daily_entries
            SET ended_at = ?
            WHERE day_id = ? AND ended_at IS NULL
        """, (closed_at, day["id"]))

        cur.execute("""
            UPDATE attendance_days
            SET status = 'closed', closed_at = ?
            WHERE id = ?
        """, (closed_at, day["id"]))

        conn.commit()
    except Exception as error:
        conn.rollback()
        print(f"❌ Eroare închidere pontaj zilnic: {error}")
        await interaction.followup.send(
            "❌ Pontajul nu a putut fi închis.",
            ephemeral=True
        )
        return
    finally:
        conn.close()

    await update_daily_panel(day["id"])

    await interaction.followup.send(
        f"🔒 Pontajul din **{day['attendance_date']}** a fost închis. "
        "Panoul și evidența au rămas salvate.",
        ephemeral=True
    )


@bot.tree.command(
    name="pontaj",
    description="Afișează ultimul pontaj creat astăzi."
)
async def pontaj(interaction: discord.Interaction):
    if not is_attendance_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Doar Lider, Co-Lider sau Discord Mod poate folosi această comandă.",
            ephemeral=True
        )
        return

    day = get_latest_today_day()

    if not day:
        await interaction.response.send_message(
            "❌ Nu există încă un pontaj creat pentru astăzi.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        embed=create_daily_embed(day["id"]),
        ephemeral=True
    )


@bot.tree.command(
    name="istoric_pontaj",
    description="Afișează istoricul detaliat al pontajului de astăzi."
)
async def istoric_pontaj(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not is_attendance_admin(interaction.user):
        await interaction.followup.send(
            "❌ Doar Lider, Co-Lider sau Discord Mod poate vedea istoricul.",
            ephemeral=True
        )
        return

    day = get_latest_today_day()

    if not day:
        await interaction.followup.send(
            "❌ Nu există pontaj pentru ziua de astăzi.",
            ephemeral=True
        )
        return

    await interaction.followup.send(
        embed=create_history_embed(day["id"]),
        ephemeral=True
    )
