import os
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
from keep_alive import keep_alive
import re

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

MONITOR_CHANNEL_ID = 1384853874967449640  # Channel where reactions happen
LOG_CHANNEL_ID = 1384854378820800675      # Channel where logs and summary go

# Store sign-ups per emoji per message
reaction_signups = defaultdict(lambda: defaultdict(set))

# Cache created threads and summary messages per message ID
created_threads = {}
thread_creation_messages = {}
summary_messages = {}

# Emoji ID mapping: emoji_id -> (display_text, color_code, emoji_obj)
# Replace emoji_obj with actual discord.PartialEmoji for real emoji if desired
EMOJI_INFO = {
    718534017082720339: ("Support", 0xFFA500, "🧡"),       # Orange heart for support
    1025015433054662676: ("CSW signed up", 0xADD8E6, "💙"), # Light Blue
    1091115981788684318: ("Renegade signed up", 0x800080, "💜"),
    1025067188102643853: ("Trident signed up", 0x0000FF, "🔱"), # Blue
    1025067230347661412: ("Athena signed up", 0x008080, "♈"),  # Tealish
    792085274149519420: ("Pathfinder signed up", 0x228B22, "🏹"), # Greenish
    663134181089607727: ("Carrier Star Wing", 0xFFD700, "✈️"),   # Gold
}

NOT_ATTENDING_EMOJI_ID = 718534017082720339  # For example, replace with real ID for :cross~1:
LATE_EMOJI = "⏳"

def extract_title_and_timestamp(message_content):
    # Split lines, ignore first if it starts with mention (@)
    lines = [line.strip() for line in message_content.splitlines() if line.strip()]
    if not lines:
        return "No Title", None
    if lines[0].startswith("<@") or lines[0].startswith("@"):
        # Skip first line if ping
        title_line = None
        for line in lines[1:]:
            if line:
                title_line = line
                break
        if not title_line:
            title_line = lines[0]
    else:
        title_line = lines[0]

    # Find a Discord timestamp in format <t:unix_timestamp:F>
    timestamp_match = re.search(r"<t:(\d+):F>", message_content)
    timestamp_str = None
    if timestamp_match:
        unix_ts = int(timestamp_match.group(1))
        dt = datetime.utcfromtimestamp(unix_ts)
        timestamp_str = dt.strftime("%A, %d %B %Y %H:%M")

    return title_line, timestamp_str

def build_summary_text(message_id, title, timestamp_str):
    emoji_data = reaction_signups[message_id]
    lines = []
    header = f"📋 Sign-Ups for **{title}**"
    if timestamp_str:
        header += f" {timestamp_str}"
    lines.append(header)

    # Sort emojis so 'Not attending' and 'Late' are last for clarity
    sorted_emojis = sorted(emoji_data.items(), key=lambda e: (
        e[0] == str(LATE_EMOJI),
        e[0] == str(NOT_ATTENDING_EMOJI_ID),
        e[0]
    ))

    for emoji_str, users in sorted_emojis:
        if not users:
            continue
        count = len(users)
        # Convert emoji_str back to ID if possible for mapping (it may be str(emoji))
        # We stored emoji as str(payload.emoji) so we have to map by string or parse
        display_text = None
        # Try match by emoji ID if possible (emoji string can be <:{name}:{id}> or unicode emoji)
        emoji_id = None
        id_match = re.match(r"<a?:\w+:(\d+)>", emoji_str)
        if id_match:
            emoji_id = int(id_match.group(1))
        if emoji_id in EMOJI_INFO:
            display_text = EMOJI_INFO[emoji_id][2] + " " + EMOJI_INFO[emoji_id][0]
        elif emoji_str == LATE_EMOJI:
            display_text = f"{count} Late"
        elif emoji_id == NOT_ATTENDING_EMOJI_ID:
            display_text = f"{count} Not attending"
        else:
            # fallback to showing raw emoji string + count + "attending"
            display_text = f"{count} {emoji_str} attending"

        # List users separated by commas
        user_list = ", ".join(sorted(users))

        lines.append(f"{display_text}: {user_list}")

    return "\n".join(lines)

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

async def get_or_create_thread_and_notify(log_channel: discord.TextChannel, message_id: int, title: str):
    if message_id in created_threads:
        return created_threads[message_id], False
    # Create thread for the reactions logs
    thread = await log_channel.create_thread(
        name=f"Reactions for msg {message_id}",
        auto_archive_duration=1440
    )
    created_threads[message_id] = thread
    # Send link message once
    link_message = await log_channel.send(f"Created thread for **{title}** → {thread.mention}")
    thread_creation_messages[message_id] = link_message
    return thread, True

async def post_or_edit_summary(log_channel, message_id, title, timestamp_str):
    summary_text = build_summary_text(message_id, title, timestamp_str)
    if message_id in summary_messages:
        try:
            await summary_messages[message_id].edit(content=summary_text)
        except discord.NotFound:
            # If message deleted, resend
            summary_messages[message_id] = await log_channel.send(summary_text)
    else:
        summary_messages[message_id] = await log_channel.send(summary_text)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel is None:
        return
    try:
        monitor_channel = guild.get_channel(payload.channel_id)
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)

    # Track reaction
    reaction_signups[payload.message_id][emoji].add(user.name)

    title, timestamp_str = extract_title_and_timestamp(message.content)

    # Create or get thread and notify once
    thread, created = await get_or_create_thread_and_notify(log_channel, message.id, title)

    # Log the reaction add inside the thread
    await thread.send(log_line(user, emoji, "added"))

    # Post or edit summary message in log channel (outside thread)
    await post_or_edit_summary(log_channel, message.id, title, timestamp_str)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel is None:
        return
    try:
        monitor_channel = guild.get_channel(payload.channel_id)
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)

    # Remove reaction
    if user.name in reaction_signups[payload.message_id][emoji]:
        reaction_signups[payload.message_id][emoji].remove(user.name)
        if not reaction_signups[payload.message_id][emoji]:
            del reaction_signups[payload.message_id][emoji]

    title, timestamp_str = extract_title_and_timestamp(message.content)

    thread, created = await get_or_create_thread_and_notify(log_channel, message.id, title)
    await thread.send(log_line(user, emoji, "removed"))

    await post_or_edit_summary(log_channel, message.id, title, timestamp_str)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
