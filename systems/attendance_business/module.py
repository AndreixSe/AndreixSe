"""Pontaj Afacere: dovezi foto la început și sfârșit, panou unic."""
import io
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from core.bot import bot
from core.database import get_db

log = logging.getLogger(__name__)
CHANNEL_ID = 1562923416108011540
ADMIN_ROLES = {1528799552075989102, 1527919721629089862, 1554072182735511623}
USER_ROLES = ADMIN_ROLES | {1562917004648648714}
TZ = ZoneInfo('Europe/Bucharest')
PURPLE = discord.Color.from_rgb(168, 85, 247)


def allowed(member, roles):
    return any(r.id in roles for r in getattr(member, 'roles', ()))


def active(user_id):
    with get_db() as db:
        return db.execute('SELECT * FROM business_attendance WHERE user_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1', (user_id,)).fetchone()


def timestamp():
    return datetime.now(TZ).isoformat(timespec='seconds')


def formatted(value):
    return datetime.fromisoformat(value).astimezone(TZ).strftime('%d.%m.%Y %H:%M:%S')


def build_embeds(row, start_filename=None, end_filename=None):
    finished = bool(row['ended_at'])
    embed = discord.Embed(title='🔒 PONTAJ AFACERE — ÎNCHEIAT' if finished else '💜 PONTAJ AFACERE — ÎNCEPUT', color=discord.Color.red() if finished else PURPLE)
    embed.add_field(name='👤 Membru', value=f"<@{row['user_id']}>", inline=False)
    embed.add_field(name='📅 Data / 🟢 Început', value=formatted(row['started_at']), inline=False)
    if finished:
        duration = max(0, int((datetime.fromisoformat(row['ended_at'])-datetime.fromisoformat(row['started_at'])).total_seconds()))
        embed.add_field(name='🔴 Încheiere', value=formatted(row['ended_at']), inline=False)
        embed.add_field(name='⏱️ Durată', value=f'{duration // 3600}h {(duration % 3600) // 60}m', inline=False)
        embed.add_field(name='👑 Închis de', value=f"<@{row['closed_by_id']}>", inline=False)
    embed.add_field(name='Status', value='🔒 ÎNCHEIAT' if finished else '🟣 ACTIV', inline=False)
    embed.add_field(name='📸 Poză început', value='Apasă pe fotografie pentru mărire.' if row['photo_url'] or start_filename else '-', inline=False)
    if start_filename:
        embed.set_image(url='attachment://' + start_filename)
    elif row['photo_url']:
        embed.set_image(url=row['photo_url'])
    embed.set_footer(text='Dominicans • Pontaj Afacere')
    embeds = [embed]
    if finished:
        second = discord.Embed(title='📸 Poză încheiere', color=discord.Color.red(), description='Apasă pe fotografie pentru mărire.' if row['end_photo_url'] or end_filename else '-')
        if end_filename:
            second.set_image(url='attachment://' + end_filename)
        elif row['end_photo_url']:
            second.set_image(url=row['end_photo_url'])
        embeds.append(second)
    return embeds


async def channel():
    return bot.get_channel(CHANNEL_ID) or await bot.fetch_channel(CHANNEL_ID)


async def read_image(photo):
    if not photo or not (photo.content_type or '').lower().startswith('image/'):
        raise ValueError('Atașează o fotografie validă.')
    data = await photo.read()
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('Fotografia depășește 8 MB.')
    ext = os.path.splitext(photo.filename or '')[1].lower()
    if ext not in {'.jpg', '.jpeg', '.png', '.webp', '.gif'}:
        ext = '.png'
    return data, ext


@bot.tree.command(name='incepepontaj', description='Începe Pontaj Afacere cu fotografie.')
@app_commands.describe(poza='Fotografia obligatorie de început')
async def incepepontaj(interaction: discord.Interaction, poza: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    if not allowed(interaction.user, USER_ROLES):
        return await interaction.followup.send('❌ Nu ai rolul necesar.', ephemeral=True)
    if active(interaction.user.id):
        return await interaction.followup.send('❌ Ai deja un pontaj activ.', ephemeral=True)
    try:
        data, ext = await read_image(poza)
        ch = await channel()
        filename = f'pontaj_start_{interaction.id}{ext}'
        with get_db() as db:
            cur = db.execute('INSERT INTO business_attendance(user_id,user_name,started_at,channel_id) VALUES (?,?,?,?)', (interaction.user.id, interaction.user.display_name, timestamp(), CHANNEL_ID))
            entry_id = cur.lastrowid
            row = db.execute('SELECT * FROM business_attendance WHERE id=?', (entry_id,)).fetchone()
        try:
            msg = await ch.send(embeds=build_embeds(row, start_filename=filename), file=discord.File(io.BytesIO(data), filename=filename))
        except Exception:
            with get_db() as db:
                db.execute('DELETE FROM business_attendance WHERE id=? AND message_id IS NULL', (entry_id,))
            raise
        with get_db() as db:
            db.execute('UPDATE business_attendance SET message_id=?,photo_url=? WHERE id=?', (msg.id, msg.attachments[0].url, entry_id))
        await interaction.followup.send('✅ Pontaj început. Panoul mov a fost publicat.', ephemeral=True)
    except ValueError as exc:
        await interaction.followup.send('❌ ' + str(exc), ephemeral=True)
    except Exception:
        log.exception('Eroare /incepepontaj')
        await interaction.followup.send('❌ Eroare la pornire. Verifică Railway.', ephemeral=True)


async def close_entry(interaction, user_id, photo=None, omit=False):
    row = active(user_id)
    if not row:
        return await interaction.followup.send('❌ Membrul nu are pontaj activ.', ephemeral=True)
    try:
        image_data = None
        ext = None
        if photo is not None:
            image_data, ext = await read_image(photo)
        elif not omit:
            raise ValueError('Fotografia de încheiere este obligatorie.')
        ch = await channel()
        msg = await ch.fetch_message(int(row['message_id']))
        # Păstrăm doar atașamentele folosite de embed-uri.
        start_attachment = msg.attachments[0] if msg.attachments else None
        filename = f'pontaj_end_{interaction.id}{ext}' if image_data else None
        with get_db() as db:
            result = db.execute('UPDATE business_attendance SET ended_at=?,closed_by_id=?,end_photo_url=? WHERE id=? AND ended_at IS NULL', (timestamp(), interaction.user.id, 'pending' if image_data else None, row['id']))
            if result.rowcount != 1:
                return await interaction.followup.send('❌ Pontajul este deja închis.', ephemeral=True)
            row = db.execute('SELECT * FROM business_attendance WHERE id=?', (row['id'],)).fetchone()
        embeds = build_embeds(row, start_filename=start_attachment.filename if start_attachment else None, end_filename=filename)
        files = [discord.File(io.BytesIO(image_data), filename=filename)] if image_data else []
        try:
            # attachments= păstrează fotografia de început, iar cea nouă este adăugată ca fișier.
            await msg.edit(embeds=embeds, attachments=[start_attachment] if start_attachment else [], files=files)
            if image_data:
                updated = await ch.fetch_message(msg.id)
                end_attachment = next((a for a in updated.attachments if a.filename == filename), None)
                if end_attachment:
                    with get_db() as db:
                        db.execute('UPDATE business_attendance SET end_photo_url=? WHERE id=?', (end_attachment.url, row['id']))
        except Exception:
            log.exception('Pontaj închis în DB, dar editarea panoului a eșuat')
            return await interaction.followup.send('⚠️ Pontaj închis în baza de date, dar panoul nu s-a putut actualiza.', ephemeral=True)
        await interaction.followup.send('✅ Pontaj încheiat. Ambele dovezi sunt în panou.', ephemeral=True)
    except ValueError as exc:
        await interaction.followup.send('❌ ' + str(exc), ephemeral=True)
    except Exception:
        log.exception('Eroare la încheierea pontajului')
        await interaction.followup.send('❌ Eroare la încheiere. Verifică Railway.', ephemeral=True)


@bot.tree.command(name='incheiepontaj', description='Încheie propriul pontaj cu fotografie.')
@app_commands.describe(poza='Fotografia obligatorie de încheiere')
async def incheiepontaj(interaction: discord.Interaction, poza: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    if not allowed(interaction.user, USER_ROLES):
        return await interaction.followup.send('❌ Nu ai rolul necesar.', ephemeral=True)
    await close_entry(interaction, interaction.user.id, photo=poza)


@bot.tree.command(name='ip', description='Conducerea închide pontajul unui membru.')
@app_commands.describe(membru='Selectează @persoana', poza='Fotografie de încheiere (opțional)', fara_poza='Bifează pentru a încheia fără poză')
async def ip(interaction: discord.Interaction, membru: discord.Member, poza: discord.Attachment | None = None, fara_poza: bool = False):
    await interaction.response.defer(ephemeral=True)
    if not allowed(interaction.user, ADMIN_ROLES):
        return await interaction.followup.send('❌ Doar Lider, Co-Lider sau Discord Mod pot folosi /ip.', ephemeral=True)
    if not poza and not fara_poza:
        return await interaction.followup.send('❌ Atașează o fotografie sau bifează fara_poza.', ephemeral=True)
    await close_entry(interaction, membru.id, photo=poza, omit=fara_poza)
