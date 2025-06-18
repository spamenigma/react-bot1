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

MONITOR_CHANNEL_ID = 1384853874967449640  # Where reactions happen
LOG_CHANNEL_ID = 1384854378820800675      # Where threads and logs go

reaction_signups = defaultdict(lambda: defaultdict(set))
summary_message_ids = {}  # Track main summary messages per original message

# Emoji role mapping by ID
EMOJI_ROLE_LABELS = {
    1025015433054662676: "CSW",
    1025067188102643853: "Trident",
    1025067230347661412: "Athena",
    1091115981788684318: "Renegade",
    792085274149519420:  "Pathfinder",
    718534017082720339:  "Not attending",
    663134181089607727:  "Late",
    0: "OPFOR"  # fallback for unicode
}

NOT_ATTENDING_ID = 718534017082720339
LATE_ID = 663134181089607727

# Helpers
def get_label(emoji):
    if hasattr(emoji, 'id') and emoji.id:
        return EMOJI_ROLE_LABELS.get(emoji.id, f"<:{emoji.name}:{emoji.id}>")
    return EMOJI_ROLE_LABELS.get(0, str(emoji))

def extract_title_and_timestamp(content):
    lines = content.splitlines()
    title = ""
    timestamp = ""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("<@"):
            continue
        if not title:
            title = line
        if not timestamp:
            match = re.search(r'<t:(\d+)(?::[a-zA-Z])?>', line)
            if match:
                timestamp = match.group(0)
    return title, timestamp

async def get_or_create_thread(log_channel, message_id, thread_title):
    existing = next((t for t in log_channel.threads if not t.archived and t.name.endswith(str(message_id))), None)
    if existing:
        return existing
    thread = await log_channel.create_thread(
        name=f"Logs for {thread_title} ({message_id})",
        auto_archive_duration=1440
    )
    return thread

def log_line(user, emoji, action):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

async def post_summary(log_channel, message_id, original_message):
    title, timestamp = extract_title_and_timestamp(original_message.content)
    heading = f"📋 **Sign-Ups for {title}**"
    if timestamp:
        heading += f" {timestamp}"

    emoji_data = reaction_signups[message_id]
    lines = [heading]

    for emoji, users in emoji_data.items():
        if not users:
            continue
        label = get_label(emoji)
        if hasattr(emoji, 'id') and emoji.id == NOT_ATTENDING_ID:
            prefix = f"**{len(users)} Not attending:**"
        elif hasattr(emoji, 'id') and emoji.id == LATE_ID:
            prefix = f"**{len(users)} Late:**"
        else:
            prefix = f"**{len(users)} {label} attending:**"
        names = ", ".join(sorted(users))
        lines.append(f"{prefix} {names}")

    content = "\n".join(lines)

    # Send or edit the summary message
    if message_id in summary_message_ids:
        try:
            msg = await log_channel.fetch_message(summary_message_ids[message_id])
            await msg.edit(content=content)
        except discord.NotFound:
            summary = await log_channel.send(content)
            summary_message_ids[message_id] = summary.id
    else:
        summary = await log_channel.send(content)
        summary_message_ids[message_id] = summary.id

@bot.event
async def on_raw_reaction_add(payload):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    channel = guild.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji

    reaction_signups[payload.message_id][emoji].add(user.name)

    title, _ = extract_title_and_timestamp(message.content)
    thread = await get_or_create_thread(log_channel, message.id, title)
    await thread.send(log_line(user, emoji, "added"))

    await post_summary(log_channel, payload.message_id, message)

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    channel = guild.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji

    users = reaction_signups[payload.message_id][emoji]
    users.discard(user.name)
    if not users:
        del reaction_signups[payload.message_id][emoji]

    title, _ = extract_title_and_timestamp(message.content)
    thread = await get_or_create_thread(log_channel, message.id, title)
    await thread.send(log_line(user, emoji, "removed"))

    await post_summary(log_channel, payload.message_id, message)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
