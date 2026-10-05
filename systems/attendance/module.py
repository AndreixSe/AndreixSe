import uuid
import discord

from core.bot import bot
from core.database import (
    get_db,
    get_setting,
    set_setting,
    format_timestamp,
    now_string,
)


# =========================================================
# ATTENDANCE HELPERS
# =========================================================

def cleanup_attendance_duplicates():
    """
    Păstrează un singur pontaj activ pentru fiecare utilizator.

    Dacă există duplicate vechi în baza de date, este păstrată
    înregistrarea cu cel mai mic ID, iar restul sunt șterse.
    """

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            DELETE FROM attendance
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM attendance
                GROUP BY user_id
            )
        """)

        conn.commit()

    except Exception as error:
        conn.rollback()
        print(f"❌ Eroare curățare duplicate pontaj: {error}")

    finally:
        conn.close()


def create_attendance_embed():

    # Curățăm eventualele duplicate vechi.
    cleanup_attendance_duplicates()

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

    # Protecție suplimentară la afișare.
    seen_users = set()

    for row in rows:

        user_id = row["user_id"]

        if user_id in seen_users:
            continue

        seen_users.add(user_id)

        lines.append(
            f"👤 <@{user_id}> — "
            f"🟢 {format_timestamp(row['started_at'])}"
        )

    embed.description = "\n".join(lines)

    return embed


# =========================================================
# ATTENDANCE VIEW
# =========================================================

class AttendanceView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

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

        # Răspundem imediat către Discord.
        await interaction.response.defer(
            ephemeral=True
        )

        conn = get_db()
        cur = conn.cursor()

        try:

            cur.execute(
                """
                SELECT *
                FROM attendance
                WHERE user_id = ?
                LIMIT 1
                """,
                (interaction.user.id,)
            )

            existing = cur.fetchone()

            if existing:

                await interaction.followup.send(
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

        except Exception as error:

            conn.rollback()

            print(
                f"❌ Eroare pornire pontaj pentru "
                f"{interaction.user.id}: {error}"
            )

            await interaction.followup.send(
                "❌ A apărut o eroare la pornirea pontajului.",
                ephemeral=True
            )

            return

        finally:
            conn.close()

        await update_attendance_panel()

        await interaction.followup.send(
            "✅ Ai început pontajul.",
            ephemeral=True
        )

    # -----------------------------------------------------
    # STOP
    # -----------------------------------------------------

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

        await interaction.response.defer(
            ephemeral=True
        )

        conn = get_db()
        cur = conn.cursor()

        try:

            cur.execute(
                """
                SELECT *
                FROM attendance
                WHERE user_id = ?
                ORDER BY started_at ASC
                LIMIT 1
                """,
                (interaction.user.id,)
            )

            existing = cur.fetchone()

            if not existing:

                await interaction.followup.send(
                    "❌ Nu ești pontat.",
                    ephemeral=True
                )

                return

            ended_at = now_string()

            session_id = str(uuid.uuid4())

            cur.execute("""
                INSERT INTO attendance_history(
                    session_id,
                    user_id,
                    user_name,
                    started_at,
                    ended_at
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                session_id,
                existing["user_id"],
                existing["user_name"]
                or interaction.user.display_name,

                existing["started_at"],
                ended_at
            ))

            # Ștergem TOATE eventualele duplicate ale utilizatorului.
            cur.execute(
                """
                DELETE FROM attendance
                WHERE user_id = ?
                """,
                (interaction.user.id,)
            )

            conn.commit()

        except Exception as error:

            conn.rollback()

            print(
                f"❌ Eroare oprire pontaj pentru "
                f"{interaction.user.id}: {error}"
            )

            await interaction.followup.send(
                "❌ A apărut o eroare la încheierea pontajului.",
                ephemeral=True
            )

            return

        finally:
            conn.close()

        await update_attendance_panel()

        await interaction.followup.send(
            "✅ Ai încheiat pontajul.",
            ephemeral=True
        )


# =========================================================
# UPDATE ATTENDANCE PANEL
# =========================================================

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

            try:
                channel = await bot.fetch_channel(
                    int(channel_id)
                )

            except Exception:
                return

        message = await channel.fetch_message(
            int(message_id)
        )

        await message.edit(
            embed=create_attendance_embed(),
            view=AttendanceView()
        )

    except discord.NotFound:

        print(
            "⚠️ Mesajul panoului de pontaj "
            "nu mai există."
        )

    except discord.Forbidden:

        print(
            "❌ Botul nu are permisiunea de a "
            "actualiza panoul de pontaj."
        )

    except Exception as error:

        print(
            f"❌ Eroare panou pontaj: {error}"
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

    # Discord primește răspuns imediat și nu mai afișează
    # "Aplicația nu a răspuns".
    await interaction.response.defer(
        ephemeral=True
    )

    try:

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

        await interaction.followup.send(
            "✅ Panoul de pontaj a fost creat.",
            ephemeral=True
        )

    except Exception as error:

        print(
            f"❌ Eroare setup pontaj: {error}"
        )

        await interaction.followup.send(
            "❌ Panoul de pontaj nu a putut fi creat.",
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

    await interaction.response.defer(
        ephemeral=True
    )

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
            SELECT *
            FROM attendance_history
            ORDER BY id DESC
            LIMIT 20
        """)

        rows = cur.fetchall()

    finally:
        conn.close()

    if not rows:

        await interaction.followup.send(
            "❌ Nu există pontaje în istoric.",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="📋 ISTORIC PONTAJ",
        color=discord.Color.blue()
    )

    for row in rows:

        user_name = (
            row["user_name"]
            or f"<@{row['user_id']}>"
        )

        embed.add_field(
            name=f"👤 {user_name}",
            value=(
                f"🟢 Început: "
                f"{format_timestamp(row['started_at']) or '-'}\n"
                f"🔴 Sfârșit: "
                f"{format_timestamp(row['ended_at']) or '-'}"
            ),
            inline=False
        )

    await interaction.followup.send(
        embed=embed,
        ephemeral=True
    )