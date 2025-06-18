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

MONITOR_CHANNEL_ID = 1384853874967449640
LOG_CHANNEL_ID = 1384854378820800675

reaction_signups = defaultdict(lambda: defaultdict(set))
posted_threads = {}

# Emoji role mapping
EMOJI_ROLE_MAP = {
    718534017082720339: ("Support", "🟧"),
    1025015433054662676: ("CSW", "<:csw:1025015433054662676>"),
    1091115981788684318: ("Renegade", "<:renegade:1091115981788684318>"),
    1025067188102643853: ("Trident", "<:trident:1025067188102643853>"),
    1025067230347661412: ("Athena", "<:athena:1025067230347661412>"),
    792085274149519420: ("Pathfinder", "<:pathfinder:792085274149519420>"),
    663134181089607727: ("OPFOR", "🏴‍☠️"),
}

CROSS_ID = 1123456789012345678  # Replace with real ID
HOURGLASS = "⏳"

async def get_or_create_thread(log_channel: discord.TextChannel, message_id: int, title: str):
    for thread in log_channel.threads:
        if thread.name.endswith(str(message_id)):
            return thread
    thread = await log_channel.create_thread(
        name=f"Logs for {title} ({message_id})",
        auto_archive_duration=1440
    )
    return thread

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

def extract_event_title(message):
    lines = [line.strip() for line in message.content.split("\n") if line.strip()]
    for line in lines:
        if line.startswith("<@"):
            continue
        return line
    return "Untitled Event"

def extract_timestamp(message):
    for word in message.content.split():
        if word.startswith("<t:"):
            return word
    return ""

def format_signup_summary(message_id: int, title: str, timestamp: str):
    lines = [f"📋 **Sign-Ups for {title} {timestamp}**"]
    emoji_data = reaction_signups[message_id]
    for emoji_id, users in emoji_data.items():
        label, icon = EMOJI_ROLE_MAP.get(emoji_id, (None, None))
        if not users:
            continue
        if label:
            summary = f"{icon} {len(users)} {label}"
        elif emoji_id == CROSS_ID:
            summary = f"❌ {len(users)} Not attending"
        elif emoji_id == HOURGLASS:
            summary = f"⏳ {len(users)} Late"
        else:
            summary = f"{emoji_id} {len(users)} signed up"
        lines.append(summary)
        for user in sorted(users):
            lines.append(f"- {user}")
        lines.append("")
    return "\n".join(lines)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    thread_title = extract_event_title(message)
    timestamp = extract_timestamp(message)
    thread = await get_or_create_thread(log_channel, message.id, thread_title)

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji
    emoji_id = getattr(emoji, "id", None) or str(emoji)
    reaction_signups[payload.message_id][emoji_id].add(user.name)

    await thread.send(log_line(user, emoji, "added"))
    summary = format_signup_summary(payload.message_id, thread_title, timestamp)
    async for msg in log_channel.history(limit=50):
        if msg.content.startswith("📋 **Sign-Ups for"):
            await msg.delete()
            break
    await log_channel.send(summary)

    if payload.message_id not in posted_threads:
        posted_threads[payload.message_id] = True
        await log_channel.send(f"🧵 Logs for **{thread_title}**: {thread.jump_url}")

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    thread_title = extract_event_title(message)
    timestamp = extract_timestamp(message)
    thread = await get_or_create_thread(log_channel, message.id, thread_title)

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji
    emoji_id = getattr(emoji, "id", None) or str(emoji)
    if user.name in reaction_signups[payload.message_id][emoji_id]:
        reaction_signups[payload.message_id][emoji_id].remove(user.name)
    if not reaction_signups[payload.message_id][emoji_id]:
        del reaction_signups[payload.message_id][emoji_id]

    await thread.send(log_line(user, emoji, "removed"))
    summary = format_signup_summary(payload.message_id, thread_title, timestamp)
    async for msg in log_channel.history(limit=50):
        if msg.content.startswith("📋 **Sign-Ups for"):
            await msg.delete()
            break
    await log_channel.send(summary)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
