import os
import re
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

MONITOR_CHANNEL_ID = 1384853874967449640  # Channel where reactions happen
LOG_CHANNEL_ID = 1384854378820800675      # Logs + threads go here

# Replace this with your custom emoji ID for :cross~1:
YOUR_CROSS_EMOJI_ID = 123456789012345678  # <-- Put your emoji ID here as an int

# Store sign-ups per emoji per message_id
reaction_signups = defaultdict(lambda: defaultdict(set))

# Map message_id to the thread object to avoid recreating threads
message_threads = {}

# Map message_id to the summary message ID in logs channel for editing
summary_messages = {}

# Regex to detect Discord timestamps like <t:1686698400>
DISCORD_TIMESTAMP_RE = re.compile(r"<t:(\d+)(:[tTdDfFR])?>")

def extract_timestamp_line(message_content: str) -> str | None:
    match = DISCORD_TIMESTAMP_RE.search(message_content)
    if not match:
        return None
    unix_ts = int(match.group(1))
    dt = datetime.utcfromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M:%S UTC")
    return dt

async def get_or_create_thread(log_channel: discord.TextChannel, message: discord.Message):
    lines = [line.strip() for line in message.content.splitlines()]
    title_line = ""

    # If first line is a mention (@...), use next non-blank line
    if lines and lines[0].startswith("@"):
        for line in lines[1:]:
            if line:
                title_line = line
                break
    else:
        if lines:
            title_line = lines[0]

    if not title_line:
        title_line = f"Message {message.id}"

    short_title = title_line[:50]  # Discord thread name limit approx 100 chars, keep safe
    thread_name = f"Reactions for msg {message.id}: {short_title}"

    # Search for existing active thread with same name
    active_threads = [thread for thread in log_channel.threads if not thread.archived]
    for thread in active_threads:
        if thread.name == thread_name:
            return thread, False

    # Create new thread
    thread = await log_channel.create_thread(
        name=thread_name,
        auto_archive_duration=1440  # 24 hours
    )
    return thread, True

def log_line(user: discord.User, emoji: discord.PartialEmoji | str, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

def post_summary_line(emoji: str, users: set[str]) -> str:
    count = len(users)

    # Match cross emoji by ID to display "not attending"
    if emoji == "❌":
        return f"❌ **{count} not attending**"

    # Handle late emoji
    if emoji == "⏳":
        plural = "s" if count > 1 else ""
        return f"⏳ **{count} late{plural}**"

    plural = "s" if count > 1 else ""
    return f"{emoji} **{count} signed up{plural}:**"

async def post_summary(log_channel: discord.TextChannel, message_id: int, message: discord.Message):
    emoji_data = reaction_signups[message_id]

    if not emoji_data:
        content = "No sign-ups yet."
    else:
        lines = []

        # Header with summary title and timestamp if any
        lines.append("📋 **Sign-up Summary**")

        first_line = message.content.splitlines()[0] if message.content else f"Message {message_id}"
        lines.append(f"**{first_line}**")

        ts_line = extract_timestamp_line(message.content)
        if ts_line:
            lines.append(f"*Event Time: {ts_line}*")

        lines.append("")  # Blank line before details

        # List each emoji with users
        for emoji, users in emoji_data.items():
            if users:
                lines.append(post_summary_line(emoji, users))
                for user in sorted(users):
                    lines.append(f"- {user}")
                lines.append("")

        content = "\n".join(lines)

    # Edit existing summary message or send new one
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

async def link_thread_message(log_channel: discord.TextChannel, thread: discord.Thread, thread_created: bool):
    if thread_created:
        link_message = f"🧵 Thread started: **{thread.name}** — {thread.jump_url}"
        await log_channel.send(link_message)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    monitored_channel = guild.get_channel(payload.channel_id)

    try:
        message = await monitored_channel.fetch_message(payload.message_id)
    except Exception:
        return

    # Get or create thread
    if payload.message_id in message_threads:
        thread = message_threads[payload.message_id]
        thread_created = False
    else:
        thread, thread_created = await get_or_create_thread(log_channel, message)
        message_threads[payload.message_id] = thread
        await link_thread_message(log_channel, thread, thread_created)

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_obj = payload.emoji

    # Match cross emoji by ID to replace with ❌
    if hasattr(emoji_obj, "id") and emoji_obj.id == 663134181089607727:
        emoji_str = "❌"
    else:
        emoji_str = str(emoji_obj)

    reaction_signups[payload.message_id][emoji_str].add(user.name)

    await thread.send(log_line(user, emoji_obj, "added"))
    await post_summary(log_channel, payload.message_id, message)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    monitored_channel = guild.get_channel(payload.channel_id)

    try:
        message = await monitored_channel.fetch_message(payload.message_id)
    except Exception:
        return

    # Get or create thread
    if payload.message_id in message_threads:
        thread = message_threads[payload.message_id]
        thread_created = False
    else:
        thread, thread_created = await get_or_create_thread(log_channel, message)
        message_threads[payload.message_id] = thread
        await link_thread_message(log_channel, thread, thread_created)

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_obj = payload.emoji

    if hasattr(emoji_obj, "id") and emoji_obj.id == 663134181089607727:
        emoji_str = "❌"
    else:
        emoji_str = str(emoji_obj)

    if user.name in reaction_signups[payload.message_id][emoji_str]:
        reaction_signups[payload.message_id][emoji_str].remove(user.name)
        if not reaction_signups[payload.message_id][emoji_str]:
            del reaction_signups[payload.message_id][emoji_str]

    await thread.send(log_line(user, emoji_obj, "removed"))
    await post_summary(log_channel, payload.message_id, message)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
