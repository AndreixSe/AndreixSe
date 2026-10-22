"""Pontaj Afacere: pontaje repetate, doua fotografii si panou individual."""
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
    return any(role.id in roles for role in getattr(member, 'roles', ()))


def active(user_id):
    with get_db() as db:
        return db.execute(
            'SELECT * FROM business_attendance WHERE user_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1',
            (user_id,),
        ).fetchone()


def timestamp():
    return datetime.now(TZ).isoformat(timespec='seconds')


def formatted(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).strftime('%d.%m.%Y %H:%M:%S')


def build_embeds(row, start_filename=None, end_filename=None):
    finished = bool(row['ended_at'])
    first = discord.Embed(
        title='🔒 PONTAJ AFACERE — ÎNCHEIAT' if finished else '💜 PONTAJ AFACERE — ÎNCEPUT',
        color=discord.Color.red() if finished else PURPLE,
    )
    first.add_field(name='👤 Membru', value=f"<@{row['user_id']}>", inline=False)
    first.add_field(name='📅 Data / 🟢 Început', value=formatted(row['started_at']), inline=False)
    if finished:
        start = datetime.fromisoformat(row['started_at'])
        end = datetime.fromisoformat(row['ended_at'])
        if start.tzinfo is None:
            start = start.replace(tzinfo=TZ)
        if end.tzinfo is None:
            end = end.replace(tzinfo=TZ)
        duration = max(0, int((end - start).total_seconds()))
        first.add_field(name='🔴 Încheiere', value=formatted(row['ended_at']), inline=False)
        first.add_field(name='⏱️ Durată', value=f'{duration // 3600}h {(duration % 3600) // 60}m', inline=False)
        first.add_field(name='👑 Închis de', value=f"<@{row['closed_by_id']}>", inline=False)
    first.add_field(name='Status', value='🔒 ÎNCHEIAT' if finished else '🟣 ACTIV', inline=False)
    first.add_field(name='📸 Poză început', value='Apasă pe fotografie pentru mărire.' if start_filename or row['photo_url'] else '-', inline=False)
    if start_filename:
        first.set_image(url=f'attachment://{start_filename}')
    elif row['photo_url']:
        first.set_image(url=row['photo_url'])
    first.set_footer(text='Dominicans • Pontaj Afacere')
    embeds = [first]
    if finished:
        second = discord.Embed(
            title='📸 Poză încheiere', color=discord.Color.red(),
            description='Apasă pe fotografie pentru mărire.' if end_filename or row['end_photo_url'] else '-',
        )
        if end_filename:
            second.set_image(url=f'attachment://{end_filename}')
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
    if not data:
        raise ValueError('Fotografia este goală.')
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
            cur = db.execute(
                'INSERT INTO business_attendance(user_id,user_name,started_at,channel_id) VALUES (?,?,?,?)',
                (interaction.user.id, interaction.user.display_name, timestamp(), CHANNEL_ID),
            )
            entry_id = cur.lastrowid
            row = db.execute('SELECT * FROM business_attendance WHERE id=?', (entry_id,)).fetchone()
        try:
            msg = await ch.send(
                embeds=build_embeds(row, start_filename=filename),
                file=discord.File(io.BytesIO(data), filename=filename),
            )
        except Exception:
            with get_db() as db:
                db.execute('DELETE FROM business_attendance WHERE id=? AND message_id IS NULL', (entry_id,))
            raise
        uploaded = next((a for a in msg.attachments if a.filename == filename), None)
        with get_db() as db:
            db.execute(
                'UPDATE business_attendance SET message_id=?,photo_url=? WHERE id=?',
                (msg.id, uploaded.url if uploaded else poza.url, entry_id),
            )
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
        if photo is None and not omit:
            raise ValueError('Fotografia de încheiere este obligatorie.')
        image_data, ext = await read_image(photo) if photo is not None and not omit else (None, None)
        ch = await channel()
        msg = None
        if row['message_id']:
            try:
                msg = await ch.fetch_message(int(row['message_id']))
            except discord.NotFound:
                log.warning('Panoul %s lipsește; îl recreez.', row['message_id'])
        filename = f'pontaj_end_{interaction.id}{ext}' if image_data is not None else None
        new_file = discord.File(io.BytesIO(image_data), filename=filename) if filename else None
        closed_at = timestamp()
        updated = dict(row)
        updated.update(ended_at=closed_at, closed_by_id=interaction.user.id, end_photo_url=None)
        if msg is not None:
            existing = list(msg.attachments)
            start_attachment = next((a for a in existing if a.filename.startswith('pontaj_start_')), None)
            embeds = build_embeds(
                updated,
                start_filename=start_attachment.filename if start_attachment else None,
                end_filename=filename,
            )
            # discord.py Message.edit accepts new discord.File objects in attachments,
            # NOT in a separate 'files' keyword argument.
            await msg.edit(embeds=embeds, attachments=[*existing, *([new_file] if new_file else [])])
        else:
            # Old failed starts can leave a DB entry without a Discord message.
            embeds = build_embeds(updated, end_filename=filename)
            if new_file:
                msg = await ch.send(embeds=embeds, file=new_file)
            else:
                msg = await ch.send(embeds=embeds)
        end_url = None
        if filename:
            refreshed = await ch.fetch_message(msg.id)
            attachment = next((a for a in refreshed.attachments if a.filename == filename), None)
            if attachment:
                end_url = attachment.url
        with get_db() as db:
            result = db.execute(
                'UPDATE business_attendance SET ended_at=?,closed_by_id=?,end_photo_url=?,message_id=? WHERE id=? AND ended_at IS NULL',
                (closed_at, interaction.user.id, end_url, msg.id, row['id']),
            )
            if result.rowcount != 1:
                return await interaction.followup.send('❌ Pontajul este deja închis.', ephemeral=True)
        await interaction.followup.send('✅ Pontaj încheiat. Panoul a fost actualizat.', ephemeral=True)
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
