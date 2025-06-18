import os
import discord
from discord.ext import commands
from datetime import datetime
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

MONITOR_CHANNEL_ID = 1384853874967449640  # Where reactions happen
LOG_CHANNEL_ID = 1384854378820800675      # Where threads and logs go

async def get_or_create_thread(log_channel: discord.TextChannel, message_id: int):
    active_threads = [thread for thread in log_channel.threads if not thread.archived]
    for thread in active_threads:
        if thread.name == f"Reactions for msg {message_id}":
            return thread
    # Not found — create a new thread in the log channel (no parent message)
    thread = await log_channel.create_thread(
        name=f"Reactions for msg {message_id}",
        auto_archive_duration=1440
    )
    return thread

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    try:
        message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    except Exception:
        return
    thread = await get_or_create_thread(log_channel, message.id)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji
    await thread.send(log_line(user, emoji, "added"))

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    try:
        message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    except Exception:
        return
    thread = await get_or_create_thread(log_channel, message.id)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji
    await thread.send(log_line(user, emoji, "removed"))

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
