import re
import discord
from discord import app_commands

from core.bot import bot
from core.database import get_db, get_setting, set_setting, now_string

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
                f"🎨 {patrol['color'] or '-'}"
            ),
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )

