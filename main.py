import os
import discord
from discord import app_commands
from discord.ext import commands

from core.bot import bot
from core.database import migrate_database

# Importurile înregistrează comenzile slash ale fiecărui sistem.
from systems.patrol.module import PatrolView
from systems.attendance.module import AttendanceView
from systems.donations.module import (
    DonationItemView,
    get_donations,
    donation_create_access_message,
    donation_full_access_message,
)

TOKEN = os.getenv("DISCORD_TOKEN")


@bot.event
async def on_ready():
    print(f"✅ Bot conectat ca {bot.user}")
    migrate_database()

    try:
        bot.add_view(PatrolView())
        bot.add_view(AttendanceView())
        for donation in get_donations():
            bot.add_view(DonationItemView(donation["id"]))
        print("✅ View-urile persistente au fost încărcate.")
    except Exception as error:
        print(f"❌ Eroare la încărcarea View-urilor: {error}")

    try:
        synced = await bot.tree.sync()
        print(f"✅ Au fost sincronizate {len(synced)} comenzi slash.")
    except Exception as error:
        print(f"❌ Eroare sincronizare comenzi: {error}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"❌ Eroare comandă prefix: {error}")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(error, app_commands.CheckFailure):
        command_name = interaction.command.name if interaction.command else ""
        message = (
            donation_create_access_message()
            if command_name == "donatie"
            else donation_full_access_message()
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return

    print(f"❌ Eroare slash command: {error}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Variabila DISCORD_TOKEN nu este configurată.")
    migrate_database()
    bot.run(TOKEN)
