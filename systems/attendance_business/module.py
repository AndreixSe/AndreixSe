"""Pontaj Afacere: comenzi individuale cu dovadă foto și închidere administrativă."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from core.bot import bot
from core.database import get_db

log = logging.getLogger(__name__)
CHANNEL_ID = 1562923416108011540
ROLE_LIDER = 1528799552075989102
ROLE_CO_LIDER = 1527919721629089862
ROLE_DISCORD_MOD = 1554072182735511623
ROLE_BUCATAR = 1562917004648648714
ADMIN_ROLES = {ROLE_LIDER, ROLE_CO_LIDER, ROLE_DISCORD_MOD}
USER_ROLES = ADMIN_ROLES | {ROLE_BUCATAR}
TZ = ZoneInfo('Europe/Bucharest')
PURPLE = discord.Color.from_rgb(168, 85, 247)


def permitted(member, roles):
    return any(role.id in roles for role in getattr(member, 'roles', ()))


def current_time():
    return datetime.now(TZ)


def stamp(value):
    return value.isoformat(timespec='seconds')


def pretty(value):
    return datetime.fromisoformat(value).astimezone(TZ).strftime('%d.%m.%Y %H:%M:%S')


def make_embed(row):
    finished = bool(row['ended_at'])
    embed = discord.Embed(
        title='🔒 PONTAJ AFACERE — ÎNCHEIAT' if finished else '💜 PONTAJ AFACERE — ÎNCEPUT',
        color=discord.Color.red() if finished else PURPLE,
    )
    embed.add_field(name='👤 Membru', value=f"<@{row['user_id']}>", inline=False)
    embed.add_field(name='📅 Data / 🟢 Început', value=pretty(row['started_at']), inline=False)
    if finished:
        start = datetime.fromisoformat(row['started_at'])
        end = datetime.fromisoformat(row['ended_at'])
        minutes = max(0, int((end - start).total_seconds()) // 60)
        embed.add_field(name='🔴 Încheiere', value=pretty(row['ended_at']), inline=False)
        embed.add_field(name='⏱️ Durată', value=f'{minutes // 60}h {minutes % 60}m', inline=False)
        embed.add_field(name='👑 Închis de', value=f"<@{row['closed_by_id']}>", inline=False)
    embed.add_field(name='Status', value='🔒 ÎNCHEIAT' if finished else '🟣 ACTIV', inline=False)
    if row['photo_url']:
        embed.add_field(name='📸 Dovadă foto', value='Fotografia de la început', inline=False)
        embed.set_image(url=row['photo_url'])
    else:
        embed.add_field(name='📸 Dovadă foto', value='-', inline=False)
    embed.set_footer(text='Dominicans • Pontaj Afacere')
    return embed


def active_entry(user_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM business_attendance WHERE user_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1',
            (user_id,),
        ).fetchone()


async def output_channel(interaction):
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(CHANNEL_ID)
    if not hasattr(channel, 'send'):
        raise ValueError('Canalul configurat nu permite trimiterea mesajelor.')
    return channel


@bot.tree.command(name='incepepontaj', description='Începe Pontaj Afacere cu fotografie obligatorie.')
@app_commands.describe(poza='Fotografia obligatorie de la începutul pontajului')
async def incepepontaj(interaction: discord.Interaction, poza: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    if not permitted(interaction.user, USER_ROLES):
        await interaction.followup.send('❌ Nu ai rolul necesar.', ephemeral=True)
        return
    if not poza.content_type or not poza.content_type.lower().startswith('image/'):
        await interaction.followup.send('❌ Atașează o fotografie validă.', ephemeral=True)
        return
    if active_entry(interaction.user.id):
        await interaction.followup.send('❌ Ai deja un pontaj activ. Încheie-l înainte să începi altul.', ephemeral=True)
        return
    try:
        channel = await output_channel(interaction)
        # Fotografia este atașată DIRECT panoului, nu trimisă separat.
        # attachment:// face ca Discord să o afișeze în embed, fără dublură.
        import io
        import os
        photo_bytes = await poza.read()
        if len(photo_bytes) > 8 * 1024 * 1024:
            await interaction.followup.send('❌ Fotografia depășește 8 MB.', ephemeral=True)
            return
        extension = os.path.splitext(poza.filename or '')[1].lower()
        if extension not in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
            extension = '.png'
        filename = f'dovada_pontaj_{interaction.id}{extension}'
        now = stamp(current_time())
        with get_db() as conn:
            cur = conn.execute(
                'INSERT INTO business_attendance(user_id, user_name, started_at, photo_url, channel_id, proof_message_id) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (interaction.user.id, interaction.user.display_name, now, None, CHANNEL_ID, None),
            )
            entry_id = cur.lastrowid
            row = conn.execute('SELECT * FROM business_attendance WHERE id = ?', (entry_id,)).fetchone()
        embed = make_embed(row)
        # Înlocuim doar câmpul foto din embed-ul inițial.
        embed.remove_field(len(embed.fields) - 1)
        embed.add_field(name='📸 Dovadă foto', value='Fotografia de la început', inline=False)
        embed.set_image(url=f'attachment://{filename}')
        try:
            message = await channel.send(
                embed=embed,
                file=discord.File(io.BytesIO(photo_bytes), filename=filename),
            )
        except Exception:
            # Dacă publicarea eșuează, eliminăm doar intrarea nouă nepublicată.
            with get_db() as conn:
                conn.execute('DELETE FROM business_attendance WHERE id = ? AND message_id IS NULL', (entry_id,))
            raise
        permanent_url = message.attachments[0].url if message.attachments else None
        with get_db() as conn:
            conn.execute(
                'UPDATE business_attendance SET message_id = ?, photo_url = ? WHERE id = ?',
                (message.id, permanent_url, entry_id),
            )
        await interaction.followup.send('✅ Ai început pontajul. Panoul mov a fost publicat.', ephemeral=True)
    except Exception:
        log.exception('Eroare /incepepontaj')
        await interaction.followup.send('❌ Nu am putut porni pontajul. Verifică logurile Railway.', ephemeral=True)


async def close_entry(interaction, target_id, hide_photo=False):
    row = active_entry(target_id)
    if row is None:
        await interaction.followup.send('❌ Persoana nu are un pontaj activ.', ephemeral=True)
        return
    with get_db() as conn:
        updated = conn.execute(
            'UPDATE business_attendance SET ended_at = ?, closed_by_id = ?, photo_url = CASE WHEN ? THEN NULL ELSE photo_url END '
            'WHERE id = ? AND ended_at IS NULL',
            (stamp(current_time()), interaction.user.id, int(hide_photo), row['id']),
        )
        if updated.rowcount != 1:
            await interaction.followup.send('❌ Pontajul a fost deja închis.', ephemeral=True)
            return
        row = conn.execute('SELECT * FROM business_attendance WHERE id = ?', (row['id'],)).fetchone()
    try:
        channel = await output_channel(interaction)
        if row['message_id']:
            msg = await channel.fetch_message(int(row['message_id']))
            embed = make_embed(row)
            if row['photo_url'] and msg.attachments:
                embed.set_image(url=f'attachment://{msg.attachments[0].filename}')
            await msg.edit(embed=embed)
        else:
            msg = await channel.send(embed=make_embed(row))
            with get_db() as conn:
                conn.execute('UPDATE business_attendance SET message_id = ? WHERE id = ?', (msg.id, row['id']))
        await interaction.followup.send('✅ Pontaj încheiat. Panoul a devenit roșu.', ephemeral=True)
    except Exception:
        log.exception('Pontaj închis în DB, dar panoul nu a putut fi actualizat: %s', row['id'])
        await interaction.followup.send('⚠️ Pontajul a fost închis în baza de date, dar panoul nu s-a putut actualiza.', ephemeral=True)


@bot.tree.command(name='incheiepontaj', description='Încheie propriul Pontaj Afacere.')
async def incheiepontaj(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not permitted(interaction.user, USER_ROLES):
        await interaction.followup.send('❌ Nu ai rolul necesar.', ephemeral=True)
        return
    await close_entry(interaction, interaction.user.id)


@bot.tree.command(name='ip', description='Închide pontajul unui membru (doar conducerea).')
@app_commands.describe(membru='Selectează @persoana', poza='Opțional: scrie - ca să nu mai apară fotografia în panou')
async def ip(interaction: discord.Interaction, membru: discord.Member, poza: str | None = None):
    await interaction.response.defer(ephemeral=True)
    if not permitted(interaction.user, ADMIN_ROLES):
        await interaction.followup.send('❌ Doar Lider, Co-Lider sau Discord Mod pot folosi /ip.', ephemeral=True)
        return
    if poza is not None and poza.strip() != '-':
        await interaction.followup.send('❌ La opțiunea poza poți scrie doar - sau o poți lăsa goală.', ephemeral=True)
        return
    await close_entry(interaction, membru.id, hide_photo=(poza is not None))
