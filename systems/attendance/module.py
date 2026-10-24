"""Pontaj Cayo individual. Inlocuieste doar systems/attendance/module.py."""
import logging
import asyncio
from datetime import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from core.bot import bot
from core.database import get_db

log = logging.getLogger(__name__)
TZ = ZoneInfo('Europe/Bucharest')
CAYO_CHANNEL = 1556701325335732264
HISTORY_CHANNEL = 1563360025244733490
DM_OWNER = 472854745862635549
OPEN_TIME = time(19, 45)
ADMINS = {1554072182735511623, 1528799552075989102, 1527919721629089862}
MEMBERS = ADMINS | {1528804522938597557}


def permitted(member, roles):
    return any(role.id in roles for role in getattr(member, 'roles', ()))


def setup_cayo_db():
    with get_db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS cayo_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_name TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            closed_by_id INTEGER,
            channel_id INTEGER,
            message_id INTEGER
        )''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_cayo_user_start ON cayo_attendance(user_id, started_at)')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_cayo_one_active ON cayo_attendance(user_id) WHERE ended_at IS NULL')
        db.execute('''CREATE TABLE IF NOT EXISTS cayo_dm_panels (
            work_date TEXT PRIMARY KEY,
            message_id INTEGER,
            status TEXT NOT NULL DEFAULT 'open'
        )''')


def now():
    return datetime.now(TZ)


def parse(value):
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def duration(start, end):
    secs = max(0, int((end - start).total_seconds()))
    return f'{secs // 3600}h {(secs % 3600) // 60}m'


def active(user_id):
    with get_db() as db:
        return db.execute('SELECT * FROM cayo_attendance WHERE user_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1', (user_id,)).fetchone()


def panel(row):
    start = parse(row['started_at'])
    finished = bool(row['ended_at'])
    embed = discord.Embed(title='🔒 PONTAJ CAYO — ÎNCHEIAT' if finished else '🟢 PONTAJ CAYO — ÎNCEPUT', color=discord.Color.red() if finished else discord.Color.green())
    embed.add_field(name='👤 Membru', value=f"<@{row['user_id']}>", inline=False)
    embed.add_field(name='📅 Data', value=start.strftime('%d.%m.%Y'), inline=False)
    embed.add_field(name='🟢 Început', value=start.strftime('%H:%M:%S'), inline=True)
    if finished:
        end = parse(row['ended_at'])
        embed.add_field(name='🔴 Încheiere', value=end.strftime('%d.%m.%Y %H:%M:%S'), inline=True)
        embed.add_field(name='⏱️ Durată totală', value=duration(start, end), inline=False)
        embed.add_field(name='👑 Închis de', value=f"<@{row['closed_by_id']}>", inline=False)
    embed.add_field(name='📊 Status', value='🔒 ÎNCHEIAT' if finished else '🟢 ACTIV', inline=False)
    embed.set_footer(text='Dominicans • Pontaj Cayo')
    return embed


async def cayo_channel():
    return bot.get_channel(CAYO_CHANNEL) or await bot.fetch_channel(CAYO_CHANNEL)


# main.py inca apeleaza bot.add_view(AttendanceView()); pastram compatibilitatea
# cu panourile VECHI, fara a mai permite pontari prin butoanele lor.
class AttendanceView(discord.ui.View):
    def __init__(self, day_id=None):
        super().__init__(timeout=None)

    @discord.ui.button(label='Pontaj vechi închis', style=discord.ButtonStyle.secondary, custom_id='attendance_start')
    async def old_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('ℹ️ Folosește /incepepontajcayo pentru noul Pontaj Cayo.', ephemeral=True)

    @discord.ui.button(label='Pontaj vechi închis', style=discord.ButtonStyle.secondary, custom_id='attendance_stop')
    async def old_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('ℹ️ Folosește /incheiepontajcayo pentru noul Pontaj Cayo.', ephemeral=True)


@bot.tree.command(name='incepepontajcayo', description='Începe un pontaj individual Cayo, fără fotografie.')
async def incepepontajcayo(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not permitted(interaction.user, MEMBERS):
        return await interaction.followup.send('❌ Nu ai rolul necesar.', ephemeral=True)
    try:
        setup_cayo_db()
        if active(interaction.user.id):
            return await interaction.followup.send('❌ Ai deja un pontaj Cayo activ.', ephemeral=True)
        ch = await cayo_channel()
        stamp = now().isoformat(timespec='seconds')
        with get_db() as db:
            # Blocheaza inserarile concurente in cadrul bazei de date.
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM cayo_attendance WHERE user_id=? AND ended_at IS NULL', (interaction.user.id,)).fetchone():
                return await interaction.followup.send('❌ Ai deja un pontaj Cayo activ.', ephemeral=True)
            cur = db.execute('INSERT INTO cayo_attendance(user_id,user_name,started_at,channel_id) VALUES (?,?,?,?)', (interaction.user.id, interaction.user.display_name, stamp, CAYO_CHANNEL))
            entry_id = cur.lastrowid
            row = db.execute('SELECT * FROM cayo_attendance WHERE id=?', (entry_id,)).fetchone()
        try:
            msg = await ch.send(embed=panel(row))
        except Exception:
            with get_db() as db:
                db.execute('DELETE FROM cayo_attendance WHERE id=? AND message_id IS NULL', (entry_id,))
            raise
        with get_db() as db:
            db.execute('UPDATE cayo_attendance SET message_id=? WHERE id=?', (msg.id, entry_id))
        await update_live_dm()
        await interaction.followup.send('✅ Pontaj Cayo început. Panoul individual a fost publicat.', ephemeral=True)
    except Exception:
        log.exception('Eroare incepepontajcayo')
        await interaction.followup.send('❌ Eroare la pornire. Verifică Railway.', ephemeral=True)


async def close_cayo(interaction, user_id):
    try:
        setup_cayo_db()
        row = active(user_id)
        if not row:
            return await interaction.followup.send('❌ Nu există pontaj Cayo activ pentru acest membru.', ephemeral=True)
        end = now().isoformat(timespec='seconds')
        with get_db() as db:
            result = db.execute('UPDATE cayo_attendance SET ended_at=?,closed_by_id=? WHERE id=? AND ended_at IS NULL', (end, interaction.user.id, row['id']))
            if result.rowcount != 1:
                return await interaction.followup.send('❌ Pontajul a fost deja încheiat.', ephemeral=True)
            updated = db.execute('SELECT * FROM cayo_attendance WHERE id=?', (row['id'],)).fetchone()
        ch = await cayo_channel()
        msg = None
        if row['message_id']:
            try:
                msg = await ch.fetch_message(int(row['message_id']))
            except discord.NotFound:
                pass
        if msg:
            try:
                await msg.edit(embed=panel(updated))
            except discord.NotFound:
                msg = None
        if msg is None:
            msg = await ch.send(embed=panel(updated))
            with get_db() as db:
                db.execute('UPDATE cayo_attendance SET message_id=? WHERE id=?', (msg.id, row['id']))
        await update_live_dm()
        await interaction.followup.send('✅ Pontaj Cayo încheiat. Durata a fost salvată.', ephemeral=True)
    except Exception:
        log.exception('Eroare inchidere Cayo')
        await interaction.followup.send('⚠️ A apărut o eroare. Verifică Railway; pontajul poate fi deja salvat.', ephemeral=True)


@bot.tree.command(name='incheiepontajcayo', description='Încheie propriul pontaj Cayo.')
async def incheiepontajcayo(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not permitted(interaction.user, MEMBERS):
        return await interaction.followup.send('❌ Nu ai rolul necesar.', ephemeral=True)
    await close_cayo(interaction, interaction.user.id)


@bot.tree.command(name='ipc', description='Conducerea încheie pontajul Cayo al unui membru.')
@app_commands.describe(membru='Membrul al cărui pontaj va fi încheiat')
async def ipc(interaction: discord.Interaction, membru: discord.Member):
    await interaction.response.defer(ephemeral=True)
    if not permitted(interaction.user, ADMINS):
        return await interaction.followup.send('❌ Doar Lider, Co-Lider și Discord Mod pot folosi /ipc.', ephemeral=True)
    await close_cayo(interaction, membru.id)


def week_history(member_id, selected):
    monday = selected - timedelta(days=selected.weekday())
    sunday = monday + timedelta(days=6)
    start_dt = datetime.combine(monday, datetime.min.time(), tzinfo=TZ)
    end_dt = start_dt + timedelta(days=7)
    with get_db() as db:
        rows = db.execute('SELECT * FROM cayo_attendance WHERE user_id=? ORDER BY started_at, id', (member_id,)).fetchall()
        # Inregistrarile istorice ale vechiului pontaj raman consultabile.
        try:
            legacy = db.execute('''SELECT e.user_id, e.started_at, e.ended_at
                FROM attendance_daily_entries e JOIN attendance_days d ON e.day_id=d.id
                WHERE e.user_id=? ORDER BY e.started_at''', (member_id,)).fetchall()
        except Exception:
            legacy = []
    entries = []
    for row in rows:
        try:
            started = parse(row['started_at'])
            if start_dt <= started < end_dt:
                entries.append((started, parse(row['ended_at']) if row['ended_at'] else None, False))
        except (ValueError, TypeError):
            log.warning('Data Cayo invalida la id=%s', row['id'])
    for row in legacy:
        try:
            started = datetime.strptime(row['started_at'], '%d.%m.%Y %H:%M:%S').replace(tzinfo=TZ)
            ended = datetime.strptime(row['ended_at'], '%d.%m.%Y %H:%M:%S').replace(tzinfo=TZ) if row['ended_at'] else None
            if start_dt <= started < end_dt:
                entries.append((started, ended, True))
        except (ValueError, TypeError):
            continue
    entries.sort(key=lambda item: item[0])
    return monday, sunday, entries


@bot.tree.command(name='istoric', description='Istoricul Cayo al unui membru pentru săptămâna unei date.')
@app_commands.describe(membru='Alege membrul', data='Data din săptămâna dorită: ZZ/LL/AAAA (opțional)')
async def istoric(interaction: discord.Interaction, membru: discord.Member, data: str | None = None):
    await interaction.response.defer(ephemeral=True)
    if not permitted(interaction.user, ADMINS):
        return await interaction.followup.send('❌ Istoricul este doar pentru conducere.', ephemeral=True)
    if interaction.channel_id != HISTORY_CHANNEL:
        return await interaction.followup.send(f'❌ Folosește /istoric doar în <#{HISTORY_CHANNEL}>.', ephemeral=True)
    try:
        selected = datetime.strptime(data, '%d/%m/%Y').date() if data else now().date()
    except ValueError:
        return await interaction.followup.send('❌ Data trebuie să fie ZZ/LL/AAAA, de exemplu 23/10/2026.', ephemeral=True)
    try:
        setup_cayo_db()
        monday, sunday, entries = week_history(membru.id, selected)
        days = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică']
        lines = []
        total = 0
        active_count = 0
        for day_index in range(7):
            day = monday + timedelta(days=day_index)
            sessions = [x for x in entries if x[0].date() == day]
            lines.append(f'**{days[day_index]} — {day:%d.%m.%Y}**')
            if not sessions:
                lines.append('— Fără pontaj')
            for started, ended, legacy in sessions:
                label = ' *(vechi)*' if legacy else ''
                if ended:
                    seconds = max(0, int((ended - started).total_seconds()))
                    total += seconds
                    lines.append(f'🟢 {started:%H:%M} → 🔴 {ended:%H:%M} • **{duration(started, ended)}**{label}')
                else:
                    active_count += 1
                    lines.append(f'🟢 {started:%H:%M} → **PONTAJ ACTIV**{label}')
            lines.append('')
        footer = f'⏱️ Total încheiat: **{total // 3600}h {(total % 3600) // 60}m**\n🟢 Pontaje active: **{active_count}**'
        title = '📋 PONTAJ CAYO — ISTORIC SĂPTĂMÂNAL'
        heading = f'👤 Membru: {membru.mention}\n📅 Săptămâna: **{monday:%d.%m.%Y} – {sunday:%d.%m.%Y}**\n\n'
        # Discord limiteaza descrierea embed la 4096 caractere.
        chunks, current = [], heading
        for line in lines:
            if len(current) + len(line) + 1 > 3500:
                chunks.append(current)
                current = ''
            current += line + '\n'
        if current:
            chunks.append(current)
        if len(chunks[-1]) + len(footer) < 4000:
            chunks[-1] += '\n' + footer
        else:
            chunks.append(footer)
        embeds = [discord.Embed(title=title if i == 0 else '📋 ISTORIC CAYO — CONTINUARE', description=part, color=discord.Color.blue()) for i, part in enumerate(chunks)]
        for i in range(0, len(embeds), 10):
            await interaction.followup.send(embeds=embeds[i:i + 10], ephemeral=True)
    except Exception:
        log.exception('Eroare istoric Cayo')
        await interaction.followup.send('❌ Eroare la istoric. Verifică Railway.', ephemeral=True)


# =========================================================
# PANOU LIVE DM — 19:45 -> 00:00, ORA ROMANIEI
# =========================================================
_dm_task = None


def work_date_for(moment):
    # Intre 00:00 si 19:44 panoul precedent nu mai este activ.
    return moment.date()


def live_embed(day, closed=False):
    with get_db() as db:
        rows = db.execute(
            'SELECT * FROM cayo_attendance WHERE ended_at IS NULL ORDER BY started_at, id'
        ).fetchall() if not closed else []
    e = discord.Embed(
        title='🔒 PONTAJ CAYO — ÎNCHIS' if closed else '🏝️ PONTAJ CAYO — LIVE',
        color=discord.Color.red() if closed else discord.Color.green()
    )
    e.add_field(name='📅 Data', value=day.strftime('%d.%m.%Y'), inline=False)
    e.add_field(name='🕒 Program', value='19:45 – 00:00 (ora României)', inline=False)
    e.add_field(name='📡 Canal conectat', value=f'<#{CAYO_CHANNEL}>', inline=False)
    if closed:
        body = 'Niciun membru activ. Pontajele rămase au fost închise automat la 00:00.'
    elif not rows:
        body = 'Momentan nu este nimeni pontat.'
    else:
        body = '\n'.join(f"🟢 <@{r['user_id']}> — {parse(r['started_at']):%H:%M}" for r in rows[:45])
        if len(rows) > 45:
            body += f'\n… și încă {len(rows) - 45} membri'
    e.add_field(name='👥 MEMBRI ACTIVI', value=body[:1024], inline=False)
    e.add_field(name='🟢 Activi', value=str(len(rows)), inline=False)
    e.set_footer(text='Dominicans • Monitorizare încheiată' if closed else 'Dominicans • Actualizare la fiecare pontare')
    return e


async def owner_dm():
    owner = bot.get_user(DM_OWNER) or await bot.fetch_user(DM_OWNER)
    return owner.dm_channel or await owner.create_dm()


async def ensure_live_dm(day, refresh=False):
    setup_cayo_db()
    key = day.isoformat()
    with get_db() as db:
        record = db.execute('SELECT * FROM cayo_dm_panels WHERE work_date=?', (key,)).fetchone()
        if record and record['status'] == 'closed':
            return
        if not record:
            db.execute('INSERT OR IGNORE INTO cayo_dm_panels(work_date,status) VALUES (?,?)', (key, 'open'))
            record = db.execute('SELECT * FROM cayo_dm_panels WHERE work_date=?', (key,)).fetchone()
    dm = await owner_dm()
    msg = None
    if record['message_id']:
        try:
            msg = await dm.fetch_message(int(record['message_id']))
        except discord.NotFound:
            pass
    if msg is None:
        msg = await dm.send(embed=live_embed(day))
        with get_db() as db:
            db.execute('UPDATE cayo_dm_panels SET message_id=? WHERE work_date=? AND status=?', (msg.id, key, 'open'))
    elif refresh:
        await msg.edit(embed=live_embed(day))


async def update_live_dm():
    moment = now()
    if moment.time() < OPEN_TIME:
        return
    try:
        await ensure_live_dm(work_date_for(moment), refresh=True)
    except (discord.Forbidden, discord.HTTPException):
        log.exception('Nu pot trimite/actualiza DM-ul Pontaj Cayo; verifica mesajele private.')
    except Exception:
        log.exception('Eroare actualizare panou Cayo DM')


async def close_day_at_midnight(day):
    # Se foloseste ora exacta 00:00 a zilei urmatoare, chiar daca botul
    # reporneste mai tarziu. Datele sunt salvate inainte de editarea Discord.
    cutoff = datetime.combine(day + timedelta(days=1), time.min, tzinfo=TZ)
    stamp = cutoff.isoformat(timespec='seconds')
    setup_cayo_db()
    with get_db() as db:
        db.execute('''UPDATE cayo_attendance SET ended_at=?, closed_by_id=?
                      WHERE ended_at IS NULL AND started_at < ?''',
                   (stamp, bot.user.id if bot.user else DM_OWNER, stamp))
        rows = db.execute('''SELECT * FROM cayo_attendance
                             WHERE ended_at=? AND closed_by_id=?''',
                          (stamp, bot.user.id if bot.user else DM_OWNER)).fetchall()
        db.execute('''UPDATE cayo_dm_panels SET status='closed' WHERE work_date=?''', (day.isoformat(),))
        record = db.execute('SELECT * FROM cayo_dm_panels WHERE work_date=?', (day.isoformat(),)).fetchone()
    # Refacem panourile individuale inchise automat.
    try:
        ch = await cayo_channel()
        for row in rows:
            try:
                msg = await ch.fetch_message(int(row['message_id'])) if row['message_id'] else None
                if msg:
                    await msg.edit(embed=panel(row))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                log.exception('Nu pot actualiza panoul Cayo #%s', row['id'])
    except (discord.Forbidden, discord.HTTPException):
        log.exception('Canal Cayo indisponibil la inchidere')
    if record and record['message_id']:
        try:
            dm = await owner_dm()
            msg = await dm.fetch_message(int(record['message_id']))
            await msg.edit(embed=live_embed(day, closed=True))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            log.exception('Nu pot inchide panoul DM Cayo pentru %s', day)


async def cayo_dm_scheduler():
    while not bot.is_closed():
        try:
            moment = now()
            setup_cayo_db()
            with get_db() as db:
                open_days = [r['work_date'] for r in db.execute(
                    "SELECT work_date FROM cayo_dm_panels WHERE status='open' AND work_date < ?",
                    (moment.date().isoformat(),)).fetchall()]
            for key in open_days:
                await close_day_at_midnight(datetime.fromisoformat(key).date())
            if moment.time() >= OPEN_TIME:
                await ensure_live_dm(moment.date())
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Eroare scheduler DM Cayo')
        await asyncio.sleep(10)


async def start_cayo_dm_scheduler():
    global _dm_task
    if _dm_task is None or _dm_task.done():
        _dm_task = asyncio.create_task(cayo_dm_scheduler())
        log.info('Scheduler DM Cayo pornit: 19:45 - 00:00 Europe/Bucharest')


bot.add_listener(start_cayo_dm_scheduler, 'on_ready')
