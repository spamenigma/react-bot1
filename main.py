import os
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

MONITOR_CHANNEL_ID = 1384853874967449640  # Where reactions happen
LOG_CHANNEL_ID = 1384854378820800675      # Where threads and logs go

# Store sign-ups per emoji per message
reaction_signups = defaultdict(lambda: defaultdict(set))
# Track summary message ID per monitored message ID in log channel
summary_messages = {}
# Track created thread IDs per monitored message ID
created_threads = {}

# Emoji IDs for matching (replace these with your actual emoji IDs)
CROSS_EMOJI_ID = 123456789012345678  # Replace with actual ID for :cross~1:
LATE_EMOJI_UNICODE = "⏳"

def describe_emoji(emoji_str: str) -> str:
    """Return descriptive label for special emojis or default."""
    if emoji_str == str(CROSS_EMOJI_ID):
        return "❌ Not attending"
    if emoji_str == LATE_EMOJI_UNICODE:
        return "⏳ Late"
    # Default to emoji itself
    return emoji_str

async def get_or_create_thread(log_channel: discord.TextChannel, message: discord.Message):
    """Get or create thread for a message, returns (thread, created_new:bool)"""
    active_threads = [thread for thread in log_channel.threads if not thread.archived]
    thread_name = f"Reactions for msg {message.id}"
    for thread in active_threads:
        if thread.name == thread_name:
            return thread, False
    # Not found — create a new thread named by first line of the message content or fallback
    first_line = message.content.splitlines()[0] if message.content else f"Message {message.id}"
    thread = await log_channel.create_thread(
        name=f"{thread_name}: {first_line[:50]}",
        auto_archive_duration=1440
    )
    return thread, True

def log_line(user: discord.User, emoji: str, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    description = {
        str(CROSS_EMOJI_ID): "Not attending",
        LATE_EMOJI_UNICODE: "Late"
    }.get(emoji, emoji)
    return f"[{time_str}] {user} {action} reaction {description}"

async def post_summary(log_channel: discord.TextChannel, message_id: int):
    table_lines = ["📋 **Sign-up Summary**"]
    emoji_data = reaction_signups[message_id]
    for emoji, users in emoji_data.items():
        if users:
            table_lines.append(f"{describe_emoji(emoji)} **{len(users)} signed up:**")
            for user in sorted(users):
                table_lines.append(f"- {user}")
            table_lines.append("")

    content = "\n".join(table_lines) if len(table_lines) > 1 else "No sign-ups yet."

    summary_msg_id = summary_messages.get(message_id)
    if summary_msg_id:
        try:
            msg = await log_channel.fetch_message(summary_msg_id)
            await msg.edit(content=content)
        except (discord.NotFound, discord.Forbidden):
            new_msg = await log_channel.send(content)
            summary_messages[message_id] = new_msg.id
    else:
        new_msg = await log_channel.send(content)
        summary_messages[message_id] = new_msg.id

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    monitor_channel = guild.get_channel(payload.channel_id)
    if not log_channel or not monitor_channel:
        return
    try:
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return
    thread, created_new = await get_or_create_thread(log_channel, message)

    # On new thread creation, post a link message in log channel (once)
    if created_new and payload.message_id not in created_threads:
        link_msg = await log_channel.send(
            f"🔗 Thread for message [{message.id}]: **{thread.name}**\n{thread.jump_url}"
        )
        created_threads[payload.message_id] = thread.id

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)

    # Track reaction signup
    reaction_signups[payload.message_id][emoji].add(user.name)

    await thread.send(log_line(user, emoji, "added"))
    await post_summary(log_channel, payload.message_id)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    monitor_channel = guild.get_channel(payload.channel_id)
    if not log_channel or not monitor_channel:
        return
    try:
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return
    thread, _ = await get_or_create_thread(log_channel, message)

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)

    # Remove reaction signup
    if user.name in reaction_signups[payload.message_id][emoji]:
        reaction_signups[payload.message_id][emoji].remove(user.name)
        if not reaction_signups[payload.message_id][emoji]:
            del reaction_signups[payload.message_id][emoji]

    await thread.send(log_line(user, emoji, "removed"))
    await post_summary(log_channel, payload.message_id)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
