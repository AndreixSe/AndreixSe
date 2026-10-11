"""Evidență M/J. Înlocuiește fostul modul de donații, fără a șterge datele vechi."""

import discord
from discord import app_commands

from core.bot import bot
from core.database import get_db, get_setting, set_setting, now, now_string

ROLE_LIDER = 1528799552075989102
ROLE_CO_LIDER = 1527919721629089862
ROLE_DISCORD_MOD = 1554072182735511623
ROLE_RESPONSABIL_MINERIT = 1558935590823796817

SETUP_ROLES = {ROLE_LIDER, ROLE_CO_LIDER, ROLE_DISCORD_MOD}
MINING_ROLES = SETUP_ROLES | {ROLE_RESPONSABIL_MINERIT}
SESSION_SETTING = "mining_current_session_id"


def has_role(interaction: discord.Interaction, roles: set[int]) -> bool:
    return (
        interaction.guild is not None
        and isinstance(interaction.user, discord.Member)
        and any(role.id in roles for role in interaction.user.roles)
    )


def fmt(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def current_session():
    raw = get_setting(SESSION_SETTING)
    if not raw:
        return None
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM mining_sessions WHERE id = ? AND ended_at IS NULL", (raw,)).fetchone()
    finally:
        conn.close()


def session_totals(session_id: int):
    conn = get_db()
    try:
        return conn.execute("""
            SELECT COUNT(*) AS activities,
                   COALESCE(SUM(sulfur), 0) AS sulfur,
                   COALESCE(SUM(iron), 0) AS iron,
                   COALESCE(SUM(buds), 0) AS buds,
                   COALESCE(SUM(joints), 0) AS joints
            FROM mining_entries WHERE session_id = ?
        """, (session_id,)).fetchone()
    finally:
        conn.close()


def history_embed(session_id: int, final: bool = False):
    totals = session_totals(session_id)
    conn = get_db()
    try:
        session = conn.execute("SELECT * FROM mining_sessions WHERE id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    label = "🔒 ISTORIC FINAL M/J" if final else "📊 ISTORIC M/J"
    embed = discord.Embed(title=label, color=discord.Color.gold())
    if session:
        embed.description = f"📅 Evidență începută la: **{session['started_at']}** (ora României)"
    embed.add_field(name="🟡 TOTAL SULF", value=fmt(totals["sulfur"]), inline=False)
    embed.add_field(name="⚙️ TOTAL FIER", value=fmt(totals["iron"]), inline=False)
    embed.add_field(name="🌿 TOTAL MUGURI", value=fmt(totals["buds"]), inline=False)
    embed.add_field(name="🚬 TOTAL JOINTURI", value=fmt(totals["joints"]), inline=False)
    embed.add_field(name="📋 Activități înregistrate", value=str(totals["activities"]), inline=False)
    if final:
        embed.add_field(name="🔒 Evidență încheiată", value=now_string(), inline=False)
    embed.set_footer(text="Dominicans • Evidență M/J")
    return embed


def entry_embed(entry_id: int, people: str, sulfur: int, iron: int,
                buds: int | None, joints: int | None, responsible_id: int, timestamp: str):
    embed = discord.Embed(title=f"⛏️ EVIDENȚĂ M/J #{entry_id}", color=discord.Color.green())
    embed.add_field(name="📅 Data", value=timestamp.split(" ")[0], inline=False)
    embed.add_field(name="👥 Persoane prezente", value=people, inline=False)
    embed.add_field(name="🟡 Sulf", value=fmt(sulfur), inline=True)
    embed.add_field(name="⚙️ Fier", value=fmt(iron), inline=True)
    embed.add_field(name="🌿 Muguri", value=fmt(buds) if buds is not None else "-", inline=True)
    embed.add_field(name="🚬 Jointuri", value=fmt(joints) if joints is not None else "-", inline=True)
    embed.add_field(name="👑 Responsabil", value=f"<@{responsible_id}>", inline=False)
    embed.set_footer(text="Dominicans • Evidență M/J • ora României")
    return embed


@bot.tree.command(name="setup_minerit", description="Încheie evidența M/J precedentă și începe una nouă.")
async def setup_minerit(interaction: discord.Interaction):
    if not has_role(interaction, SETUP_ROLES):
        await interaction.response.send_message("❌ Doar Lider, Co-Lider sau Discord Mod poate începe o evidență M/J.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    old = current_session()
    try:
        # Publicăm istoricul final înainte de resetare. Dacă Discord dă eroare,
        # sesiunea veche rămâne activă și nu se pierde evidența.
        if old:
            await interaction.channel.send(embed=history_embed(old["id"], final=True))

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            if old:
                cur.execute("UPDATE mining_sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
                            (now_string(), old["id"]))
            cur.execute("INSERT INTO mining_sessions(started_at, channel_id) VALUES (?, ?)",
                        (now_string(), interaction.channel_id))
            new_id = cur.lastrowid
            cur.execute("""
                INSERT INTO settings(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (SESSION_SETTING, str(new_id)))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        await interaction.channel.send(embed=history_embed(new_id))
        await interaction.followup.send("✅ Evidența M/J nouă a început. Totalurile sunt de la zero; istoricul vechi a rămas salvat.", ephemeral=True)
    except (discord.Forbidden, discord.HTTPException) as error:
        await interaction.followup.send(f"❌ Nu am putut publica panoul în canal. Verifică permisiunile botului. ({error})", ephemeral=True)
    except Exception as error:
        print(f"❌ Eroare setup M/J: {error}")
        await interaction.followup.send("❌ Eroare la crearea evidenței M/J. Verifică logurile Railway.", ephemeral=True)


@bot.tree.command(name="minerit", description="Înregistrează o activitate M/J cu participanți și cantități.")
@app_commands.describe(
    persoane="Persoanele prezente (poți scrie @mențiuni sau nume separate prin virgulă)",
    sulf="Cantitatea totală de sulf a grupului",
    fier="Cantitatea totală de fier a grupului",
    muguri="Cantitatea de muguri (opțional; necompletat = -)",
    jointuri="Cantitatea de jointuri (opțional; necompletat = -)",
)
async def minerit(interaction: discord.Interaction, persoane: str, sulf: int, fier: int,
                  muguri: int | None = None, jointuri: int | None = None):
    if not has_role(interaction, MINING_ROLES):
        await interaction.response.send_message("❌ Nu ai rolul Responsabil Minerit, Lider, Co-Lider sau Discord Mod.", ephemeral=True)
        return
    if not persoane.strip() or len(persoane) > 1024:
        await interaction.response.send_message("❌ Completează persoanele prezente (maximum 1024 caractere).", ephemeral=True)
        return
    values = (sulf, fier, muguri, jointuri)
    if any(value is not None and value < 0 for value in values):
        await interaction.response.send_message("❌ Cantitățile nu pot fi negative.", ephemeral=True)
        return
    if not any(value for value in values if value is not None):
        await interaction.response.send_message("❌ Introdu cel puțin o cantitate mai mare decât zero.", ephemeral=True)
        return
    session = current_session()
    if not session:
        await interaction.response.send_message("❌ Nu există evidență M/J activă. Un Lider trebuie să folosească `/setup_minerit`.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    timestamp = now_string()
    try:
        channel = bot.get_channel(int(session["channel_id"]))
        if channel is None:
            channel = await bot.fetch_channel(int(session["channel_id"]))
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO mining_entries(session_id, created_at, people, sulfur, iron, buds, joints, responsible_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (session["id"], timestamp, persoane.strip(), sulf, fier,
                  muguri or 0, jointuri or 0, interaction.user.id))
            entry_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        try:
            message = await channel.send(embed=entry_embed(entry_id, persoane.strip(), sulf, fier,
                                                             muguri, jointuri, interaction.user.id, timestamp))
        except Exception:
            # Nu lăsăm în totaluri o activitate pentru care nu s-a creat panoul.
            conn = get_db()
            try:
                conn.execute("DELETE FROM mining_entries WHERE id = ?", (entry_id,))
                conn.commit()
            finally:
                conn.close()
            raise

        conn = get_db()
        try:
            conn.execute("UPDATE mining_entries SET message_id = ? WHERE id = ?", (message.id, entry_id))
            conn.commit()
        finally:
            conn.close()
        await interaction.followup.send(f"✅ Activitatea M/J #{entry_id} a fost înregistrată în <#{session['channel_id']}>.", ephemeral=True)
    except Exception as error:
        print(f"❌ Eroare înregistrare M/J: {error}")
        await interaction.followup.send("❌ Nu am putut publica activitatea. Verifică permisiunile și logurile Railway.", ephemeral=True)


@bot.tree.command(name="minerit_istoric", description="Arată totalurile M/J din evidența curentă.")
async def minerit_istoric(interaction: discord.Interaction):
    if not has_role(interaction, MINING_ROLES):
        await interaction.response.send_message("❌ Nu ai acces la istoricul M/J.", ephemeral=True)
        return
    session = current_session()
    if not session:
        await interaction.response.send_message("❌ Nu există evidență M/J activă. Folosește mai întâi `/setup_minerit`.", ephemeral=True)
        return
    await interaction.response.send_message(embed=history_embed(session["id"]), ephemeral=True)
