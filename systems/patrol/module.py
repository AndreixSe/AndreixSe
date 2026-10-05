import re
import discord
from discord import app_commands

from core.bot import bot
from core.database import get_db, get_setting, set_setting, now_string, now


# =========================================================
# HELPERS
# =========================================================

def parse_user_mentions(text):
    if not text:
        return []

    result = []
    for user_id in re.findall(r"<@!?(\d+)>", text):
        user_id = int(user_id)
        if user_id not in result:
            result.append(user_id)
    return result


def get_current_patrol_session_id():
    return get_setting("patrol_session_id")


def get_patrol(patrol_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM patrols WHERE id = ?", (patrol_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_patrol_by_message_id(message_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM patrols WHERE message_id = ? ORDER BY id DESC LIMIT 1",
        (str(message_id),)
    )
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


def create_patrol_embed(patrol):
    people = get_patrol_people(patrol["id"])
    people_text = "\n".join(
        (person["mention"] or f"<@{person['user_id']}>")
        for person in people
    ) or "Nicio persoană"

    active = bool(patrol["active"])
    status = "🟢 PATRULĂ ACTIVĂ" if active else "🔒 PATRULĂ ÎNCHEIATĂ"

    embed = discord.Embed(
        title="🚓 PATRULĂ",
        description=status,
        color=discord.Color.blue() if active else discord.Color.dark_grey()
    )

    embed.add_field(name="👥 PERSOANE", value=people_text, inline=False)
    embed.add_field(name="📅 DATA", value=patrol["patrol_date"] or "-", inline=True)
    embed.add_field(name="🕐 ORA", value=patrol["patrol_time"] or "-", inline=True)
    embed.add_field(name="🚗 NR AUTO", value=str(patrol["cars_count"] or 0), inline=True)
    embed.add_field(name="🎨 CULOARE", value=patrol["color"] or "-", inline=False)
    embed.add_field(name="👤 NR PERS", value=str(len(people)), inline=True)

    if not active and patrol["ended_at"]:
        embed.add_field(name="🏁 ÎNCHEIATĂ LA", value=patrol["ended_at"], inline=True)

    if patrol["image_url"]:
        embed.add_field(
            name="📸 POZA",
            value=f"[Vezi poza în rezoluție completă]({patrol['image_url']})",
            inline=False
        )
        embed.set_image(url=patrol["image_url"])

    embed.set_footer(text=f"Patrulă #{patrol['id']}")
    return embed


async def save_patrol_image(channel, attachment):
    if attachment is None:
        return None

    try:
        file = await attachment.to_file()
        message = await channel.send(content="📸 Poza patrulei", file=file)
        if message.attachments:
            return message.attachments[0].url
    except Exception as e:
        print(f"❌ Eroare salvare poza: {e}")

    return None


async def finish_patrol(patrol_id):
    patrol = get_patrol(patrol_id)
    if patrol is None or not patrol["active"]:
        return None

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE patrols
        SET active = 0, ended_at = ?
        WHERE id = ? AND active = 1
    """, (now_string(), patrol_id))
    conn.commit()
    conn.close()
    return get_patrol(patrol_id)


# =========================================================
# VIEW PE FIECARE PATRULĂ
# =========================================================

class PatrolView(discord.ui.View):
    def __init__(self, ended=False):
        super().__init__(timeout=None)
        if ended:
            for item in self.children:
                item.disabled = True

    @discord.ui.button(
        label="Încheie patrula",
        style=discord.ButtonStyle.danger,
        emoji="🔴",
        custom_id="patrol_finish_button"
    )
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        patrol = get_patrol_by_message_id(interaction.message.id)

        if patrol is None:
            await interaction.response.send_message(
                "❌ Nu am găsit această patrulă în baza de date.",
                ephemeral=True
            )
            return

        if not patrol["active"]:
            await interaction.response.send_message(
                "❌ Patrula este deja încheiată.",
                ephemeral=True
            )
            return

        updated = await finish_patrol(patrol["id"])

        if updated is None:
            await interaction.response.send_message(
                "❌ Patrula nu a putut fi încheiată.",
                ephemeral=True
            )
            return

        await interaction.response.edit_message(
            embed=create_patrol_embed(updated),
            view=PatrolView(ended=True)
        )


# =========================================================
# SETUP PATRULE - ÎNCEPE O SESIUNE / ISTORIC NOU
# =========================================================

@bot.tree.command(
    name="setup_patrule",
    description="Pornește o sesiune nouă de patrule în canalul curent."
)
async def setup_patrule(interaction: discord.Interaction):
    session_id = now().strftime("%Y%m%d%H%M%S%f")

    set_setting("patrol_panel_channel_id", str(interaction.channel.id))
    set_setting("patrol_session_id", session_id)

    embed = discord.Embed(
        title="🚓 PATRULE",
        description=(
            f"📅 **{now().strftime('%d.%m.%Y')}**\n"
            "Sesiune nouă de patrule.\n\n"
            "Patrulele postate de acum înainte vor apărea în istoricul acestei sesiuni."
        ),
        color=discord.Color.blue()
    )

    message = await interaction.channel.send(embed=embed)
    set_setting("patrol_panel_message_id", str(message.id))

    await interaction.response.send_message(
        "✅ Sesiunea de patrule a fost pornită. Istoricul începe de acum.",
        ephemeral=True
    )


# =========================================================
# ÎNCEPE PATRULA - FĂRĂ LIMITĂ DE PATRULE ACTIVE
# =========================================================

@bot.tree.command(name="incepe_patrula", description="Postează o patrulă nouă.")
@app_commands.describe(
    persoane="Menționează persoanele: @Ion @Vasile @Andrei",
    data="Data, exemplu: 05.10.2026",
    ora="Ora, exemplu: 14:30",
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
    await interaction.response.defer(ephemeral=True)

    session_id = get_current_patrol_session_id()
    panel_channel_id = get_setting("patrol_panel_channel_id")

    if not session_id or not panel_channel_id:
        await interaction.followup.send(
            "❌ Rulează mai întâi `/setup_patrule`.",
            ephemeral=True
        )
        return

    user_ids = parse_user_mentions(persoane)
    if not user_ids:
        await interaction.followup.send(
            "❌ Nu am găsit nicio mențiune validă.",
            ephemeral=True
        )
        return

    members = []
    for user_id in user_ids:
        member = interaction.guild.get_member(user_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user_id)
            except Exception:
                member = None
        if member is not None:
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

    if poza is not None and poza.content_type not in [
        "image/png", "image/jpeg", "image/jpg", "image/webp"
    ]:
        await interaction.followup.send(
            "❌ Poza trebuie să fie PNG, JPG, JPEG sau WEBP.",
            ephemeral=True
        )
        return

    panel_channel = bot.get_channel(int(panel_channel_id))
    if panel_channel is None:
        await interaction.followup.send(
            "❌ Nu am găsit canalul configurat pentru patrule.",
            ephemeral=True
        )
        return

    image_url = await save_patrol_image(panel_channel, poza) if poza else None

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO patrols(
            name, people_count, cars_count, color,
            patrol_date, patrol_time, image_url,
            started_at, ended_at,
            created_by_id, created_by_name,
            active, session_id, message_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "Patrulă", len(members), nr_auto, culoare,
        data, ora, image_url,
        now_string(), None,
        interaction.user.id, interaction.user.display_name,
        1, session_id, None
    ))
    patrol_id = cur.lastrowid

    for member in members:
        cur.execute("""
            INSERT INTO patrol_people(
                patrol_id, user_id, user_name, display_name, mention
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            patrol_id, member.id, member.display_name,
            member.display_name, member.mention
        ))

    conn.commit()
    conn.close()

    patrol = get_patrol(patrol_id)
    patrol_message = await panel_channel.send(
        embed=create_patrol_embed(patrol),
        view=PatrolView()
    )

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE patrols SET message_id = ? WHERE id = ?",
        (str(patrol_message.id), patrol_id)
    )
    conn.commit()
    conn.close()

    await interaction.followup.send(
        f"✅ Patrula #{patrol_id} a fost postată. Poți posta și alte patrule fără limită.",
        ephemeral=True
    )


# =========================================================
# ÎNCHEIE PATRULA PRIN COMANDĂ
# =========================================================

@bot.tree.command(
    name="incheie_patrula",
    description="Încheie o patrulă după numărul ei."
)
@app_commands.describe(patrula_id="Numărul patrulei, afișat jos în panou")
async def incheie_patrula(interaction: discord.Interaction, patrula_id: int):
    patrol = get_patrol(patrula_id)

    if patrol is None:
        await interaction.response.send_message("❌ Patrula nu există.", ephemeral=True)
        return

    if not patrol["active"]:
        await interaction.response.send_message("❌ Patrula este deja încheiată.", ephemeral=True)
        return

    updated = await finish_patrol(patrula_id)

    if updated is None:
        await interaction.response.send_message(
            "❌ Patrula nu a putut fi încheiată.",
            ephemeral=True
        )
        return

    channel_id = get_setting("patrol_panel_channel_id")
    if updated["message_id"] and channel_id:
        try:
            channel = bot.get_channel(int(channel_id))
            message = await channel.fetch_message(int(updated["message_id"]))
            await message.edit(
                embed=create_patrol_embed(updated),
                view=PatrolView(ended=True)
            )
        except Exception as e:
            print(f"❌ Nu am putut actualiza mesajul patrulei: {e}")

    await interaction.response.send_message(
        f"🔴 Patrula #{patrula_id} a fost încheiată.",
        ephemeral=True
    )


# =========================================================
# VEZI PATRULA
# =========================================================

@bot.tree.command(name="patrula", description="Afișează o patrulă după numărul ei.")
@app_commands.describe(patrula_id="Numărul patrulei")
async def patrula(interaction: discord.Interaction, patrula_id: int):
    row = get_patrol(patrula_id)
    if row is None:
        await interaction.response.send_message("❌ Patrula nu există.", ephemeral=True)
        return

    await interaction.response.send_message(
        embed=create_patrol_embed(row),
        ephemeral=True
    )


# =========================================================
# ISTORIC - DOAR SESIUNEA PORNITĂ DE ULTIMUL /setup_patrule
# =========================================================

@bot.tree.command(
    name="istoric_patrule",
    description="Afișează patrulele din sesiunea curentă."
)
async def istoric_patrule(interaction: discord.Interaction):
    session_id = get_current_patrol_session_id()

    if not session_id:
        await interaction.response.send_message(
            "❌ Nu există o sesiune de patrule. Rulează `/setup_patrule`.",
            ephemeral=True
        )
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT *
        FROM patrols
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT 20
    """, (session_id,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message(
            "❌ Nu există patrule în sesiunea curentă.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="📋 ISTORIC PATRULE",
        description=f"📅 **{now().strftime('%d.%m.%Y')}**",
        color=discord.Color.blue()
    )

    for row in rows:
        status = "🟢 ACTIVĂ" if row["active"] else "🔒 ÎNCHEIATĂ"
        people = get_patrol_people(row["id"])
        people_text = " ".join(
            p["mention"] or f"<@{p['user_id']}>"
            for p in people
        ) or "-"

        value = (
            f"👥 {people_text}\n"
            f"📅 {row['patrol_date'] or '-'} • 🕐 {row['patrol_time'] or '-'}\n"
            f"🚗 Auto: {row['cars_count'] or 0} • 🎨 {row['color'] or '-'}"
        )
        if row["ended_at"]:
            value += f"\n🏁 Încheiată: {row['ended_at']}"

        embed.add_field(
            name=f"🚓 Patrula #{row['id']} — {status}",
            value=value,
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)
