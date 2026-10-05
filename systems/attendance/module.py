import discord
from core.bot import bot
from core.database import get_db, get_setting, set_setting, format_timestamp, now_string

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
            f"🟢 {format_timestamp(row['started_at'])}"
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
            existing["user_name"] or interaction.user.display_name,
            format_timestamp(existing["started_at"]),
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
            name=f"👤 {row['user_name'] or f"<@{row['user_id']}>"}",
            value=(
                f"🟢 Început: {format_timestamp(row['started_at']) or '-'}\n"
                f"🔴 Sfârșit: {format_timestamp(row['ended_at']) or '-'}"
            ),
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


