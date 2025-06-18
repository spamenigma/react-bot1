import os
import discord
from discord.ext import commands, tasks
from datetime import datetime
from collections import defaultdict
import asyncio
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

MONITOR_CHANNEL_ID = 1384853874967449640
LOG_CHANNEL_ID = 1384854378820800675

# Track signups: message_id -> emoji -> set(user_id)
reaction_signups = defaultdict(lambda: defaultdict(set))
# Track debounce tasks: message_id -> asyncio.Task
debounce_tasks = {}
# Track last summary message to delete: message_id -> discord.Message
last_summary_messages = {}

async def get_or_create_thread(log_channel: discord.TextChannel, message_id: int):
    active_threads = [thread for thread in log_channel.threads if not thread.archived]
    for thread in active_threads:
        if thread.name == f"Reactions for msg {message_id}":
            return thread
    return await log_channel.create_thread(
        name=f"Reactions for msg {message_id}",
        auto_archive_duration=1440
    )

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    emoji_str = f"<:{emoji.name}:{emoji.id}>" if emoji.id else emoji.name
    return f"[{time_str}] {user} {action} reaction {emoji_str}"

def format_user_mention(user_id):
    return f"<@{user_id}>"

def format_summary(message_id):
    emoji_data = reaction_signups[message_id]
    if not emoji_data:
        return "📋 **Sign-up Summary**\n_No current sign-ups._"

    lines = ["📋 **Sign-up Summary**"]
    for emoji, users in emoji_data.items():
        if not users:
            continue
        emoji_display = emoji
        lines.append(f"{emoji_display} **{len(users)} signed up:**")

        mentions = [format_user_mention(uid) for uid in sorted(users)]
        # Format into 4 columns
        row = []
        for i, mention in enumerate(mentions, 1):
            row.append(mention)
            if i % 4 == 0 or i == len(mentions):
                lines.append(" | ".join(row))
                row = []
        lines.append("")  # blank line after each emoji block
    return "\n".join(lines)

async def update_summary(message_id, thread):
    await asyncio.sleep(2)  # debounce delay
    summary = format_summary(message_id)
    # Delete previous summary if exists
    if message_id in last_summary_messages:
        try:
            await last_summary_messages[message_id].delete()
        except discord.HTTPException:
            pass
    # Send new summary
    new_msg = await thread.send(summary)
    last_summary_messages[message_id] = new_msg
    debounce_tasks.pop(message_id, None)

async def schedule_summary_update(message_id, thread):
    if message_id in debounce_tasks:
        debounce_tasks[message_id].cancel()
    debounce_tasks[message_id] = asyncio.create_task(update_summary(message_id, thread))

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    try:
        message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    except Exception as e:
        print(f"Error fetching message: {e}")
        return

    thread = await get_or_create_thread(log_channel, message.id)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)

    reaction_signups[payload.message_id][emoji].add(user.id)

    await thread.send(log_line(user, payload.emoji, "added"))
    await schedule_summary_update(payload.message_id, thread)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    try:
        message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    except Exception as e:
        print(f"Error fetching message: {e}")
        return

    thread = await get_or_create_thread(log_channel, message.id)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)

    if user.id in reaction_signups[payload.message_id][emoji]:
        reaction_signups[payload.message_id][emoji].remove(user.id)
        if not reaction_signups[payload.message_id][emoji]:
            del reaction_signups[payload.message_id][emoji]

    await thread.send(log_line(user, payload.emoji, "removed"))
    await schedule_summary_update(payload.message_id, thread)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
