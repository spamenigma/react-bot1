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

MONITOR_CHANNEL_ID = 1384853874967449640
LOG_CHANNEL_ID = 1384854378820800675

reaction_signups = defaultdict(lambda: defaultdict(set))
message_threads = {}  # message_id -> thread object

# Emoji ID map to label and color (hex)
EMOJI_MAP = {
    663134181089607727: ("Support", 0xE67E22),            # orange
    1025015433054662676: ("CSW", 0x85C1E9),              # lighter blue
    1025067188102643853: ("Trident", 0x1F8BFF),           # blue
    1025067230347661412: ("Athena", 0x9B59B6),            # purple
    1091115981788684318: ("Renegade", 0xE74C3C),          # red
    792085274149519420: ("Pathfinder", 0xF39C12),          # gold/orange
    718534017082720339: ("Not attending", 0x7F8C8D),      # gray
}
LATE_EMOJI = "⏳"
LATE_LABEL = "Late"
LATE_COLOR = 0x95A5A6

def get_label_and_color(emoji_obj):
    emoji_id = getattr(emoji_obj, "id", None)
    if emoji_id in EMOJI_MAP:
        return EMOJI_MAP[emoji_id]
    if str(emoji_obj) == LATE_EMOJI:
        return LATE_LABEL, LATE_COLOR
    return str(emoji_obj), 0xBDC3C7  # default gray

def extract_title_and_timestamp(message):
    lines = message.content.splitlines()
    # Find first non-empty line that does not start with a mention <@...>
    title = ""
    for line in lines:
        line = line.strip()
        if line and not line.startswith("<@"):
            title = line
            break

    # Extract only :F: format timestamp (ignore :R:)
    timestamp_str = ""
    ts_match = re.search(r"<t:(\d+):F>", message.content)
    if ts_match:
        ts = int(ts_match.group(1))
        timestamp_str = datetime.utcfromtimestamp(ts).strftime("%A, %d %B %Y %H:%M")
    return title, timestamp_str

async def get_or_create_thread(log_channel, message, message_id):
    # Check cached thread first
    if message_id in message_threads and not message_threads[message_id].archived:
        return message_threads[message_id], False
    # Find existing thread by suffix
    for thread in log_channel.threads:
        if not thread.archived and thread.name.endswith(str(message_id)):
            message_threads[message_id] = thread
            return thread, False

    # Create new thread with the extracted title
    title, timestamp = extract_title_and_timestamp(message)
    thread_name = f"Reactions for msg {message_id}"
    if title:
        thread_name = f"{title} → Reactions for msg {message_id}"

    thread = await log_channel.create_thread(
        name=thread_name,
        auto_archive_duration=1440
    )
    message_threads[message_id] = thread
    return thread, True

def format_summary(message, message_id):
    title, timestamp = extract_title_and_timestamp(message)
    header = f"📋 Sign-Ups for {title}"
    if timestamp:
        header += f" {timestamp}"
    lines = [header]

    emoji_data = reaction_signups[message_id]
    # Sort emojis by label for consistency
    sorted_emojis = sorted(emoji_data.items(), key=lambda e: get_label_and_color(e[0])[0].lower())

    for emoji, users in sorted_emojis:
        if not users:
            continue
        label, _ = get_label_and_color(emoji)
        count = len(users)
        # Format line differently for special labels
        if label == LATE_LABEL:
            line = f"{count} {label.lower()}: {', '.join(sorted(users))}"
        elif label == "Not attending":
            line = f"{count} {label.lower()}: {', '.join(sorted(users))}"
        else:
            line = f"{count} {label} attending: {', '.join(sorted(users))}"
        lines.append(line)

    return "\n".join(lines)

def log_line(user, emoji, action):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

@bot.event
async def on_raw_reaction_add(payload):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    channel = guild.get_channel(payload.channel_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)

    try:
        message = await channel.fetch_message(payload.message_id)
    except Exception:
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji

    # Track sign-up
    reaction_signups[payload.message_id][emoji].add(user.name)

    # Create or get thread
    thread, created = await get_or_create_thread(log_channel, message, payload.message_id)

    # If new thread created, post link message in logs channel once
    if created:
        link = thread.jump_url
        await log_channel.send(f"Created thread for **{thread.name}** → {link}")

    # Log reaction in thread
    await thread.send(log_line(user, emoji, "added"))

    # Update summary message in logs channel
    summary_text = format_summary(message, payload.message_id)
    # Store or update summary message per message ID
    if payload.message_id not in message_summaries:
        msg = await log_channel.send(summary_text)
        message_summaries[payload.message_id] = msg
    else:
        try:
            await message_summaries[payload.message_id].edit(content=summary_text)
        except discord.NotFound:
            # Message deleted? send new
            msg = await log_channel.send(summary_text)
            message_summaries[payload.message_id] = msg

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    channel = guild.get_channel(payload.channel_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)

    try:
        message = await channel.fetch_message(payload.message_id)
    except Exception:
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji

    # Remove sign-up
    if user.name in reaction_signups[payload.message_id][emoji]:
        reaction_signups[payload.message_id][emoji].remove(user.name)
        if not reaction_signups[payload.message_id][emoji]:
            del reaction_signups[payload.message_id][emoji]

    thread, created = await get_or_create_thread(log_channel, message, payload.message_id)

    await thread.send(log_line(user, emoji, "removed"))

    # Update summary message in logs channel
    summary_text = format_summary(message, payload.message_id)
    if payload.message_id not in message_summaries:
        msg = await log_channel.send(summary_text)
        message_summaries[payload.message_id] = msg
    else:
        try:
            await message_summaries[payload.message_id].edit(content=summary_text)
        except discord.NotFound:
            msg = await log_channel.send(summary_text)
            message_summaries[payload.message_id] = msg

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
