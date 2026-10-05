import discord
from discord import app_commands

from core.bot import bot
from core.database import get_db, get_setting, set_setting, now_string

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


