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
LOG_CHANNEL_ID = 1384854378820800675      # Where logs and summary go

# Signups: message_id -> emoji (as ID or name) -> set of user names
reaction_signups = defaultdict(lambda: defaultdict(set))

# Store thread and summary message references
reaction_threads = {}     # message_id -> thread
summary_messages = {}     # message_id -> summary msg

# Emoji role mapping with label, emoji string, and optional color
EMOJI_ROLES = {
    718534017082720339: ("Support", "🟧"),
    1025015433054662676: ("CSW", "<:csw:1025015433054662676>"),
    1091115981788684318: ("Renegade", "<:renegade:1091115981788684318>"),
    1025067188102643853: ("Trident", "<:trident:1025067188102643853>"),
    1025067230347661412: ("Athena", "<:athena:1025067230347661412>"),
    792085274149519420: ("Pathfinder", "<:pathfinder:792085274149519420>"),
    "🏴‍☠️": ("OPFOR", "🏴‍☠️"),
    663134181089607727: ("Not attending", "❌"),
    "⏳": ("Late", "⏳"),
}

def get_summary_title(original_msg):
    lines = original_msg.content.splitlines()
    for line in lines:
        if line.strip() and not line.strip().startswith("<@"):
            title = line.strip()
            break
    else:
        title = "Event"

    # Try to extract Discord timestamp (e.g. <t:1234567890:R>)
    ts_parts = [part for part in lines if "<t:" in part]
    timestamp = ts_parts[0] if ts_parts else ""
    return f"Sign-Ups for {title} {timestamp}".strip()

def get_or_create_thread(log_channel: discord.TextChannel, original_msg, message_id: int):
    existing = [t for t in log_channel.threads if not t.archived and str(message_id) in t.name]
    if existing:
        return existing[0]
    return log_channel.create_thread(name=f"Reactions for msg {message_id}", auto_archive_duration=1440)

def log_line(user: discord.User, emoji_obj, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    emoji_str = emoji_obj.name
    if hasattr(emoji_obj, "id") and emoji_obj.id:
        emoji_str = f"<:{emoji_obj.name}:{emoji_obj.id}>"
    return f"[{time_str}] {user} {action} reaction {emoji_str}"

def get_emoji_key(emoji):
    return emoji.id if emoji.id else emoji.name

async def update_summary(log_channel, original_msg, message_id):
    emoji_data = reaction_signups[message_id]
    lines = [f"📋 **{get_summary_title(original_msg)}**"]
    for emoji_key, users in emoji_data.items():
        if not users:
            continue
        label, icon = EMOJI_ROLES.get(emoji_key, ("", str(emoji_key)))
        label_text = f"{len(users)} {label}" if label else f"{icon} {len(users)} signed up"
        lines.append(f"**{label_text}**")
        for user in sorted(users):
            lines.append(f"- {user}")
        lines.append("")
    text = "\n".join(lines)

    if message_id in summary_messages:
        try:
            await summary_messages[message_id].edit(content=text)
            return
        except Exception:
            pass

    summary = await log_channel.send(text)
    summary_messages[message_id] = summary

    if message_id not in reaction_threads:
        thread = await get_or_create_thread(log_channel, original_msg, message_id)
        reaction_threads[message_id] = thread
        await log_channel.send(f"📌 Thread for **{get_summary_title(original_msg)}** → {thread.jump_url}")

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_key = get_emoji_key(payload.emoji)

    reaction_signups[payload.message_id][emoji_key].add(user.name)

    thread = reaction_threads.get(payload.message_id)
    if not thread:
        thread = await get_or_create_thread(log_channel, message, payload.message_id)
        reaction_threads[payload.message_id] = thread
    await thread.send(log_line(user, payload.emoji, "added"))

    await update_summary(log_channel, message, payload.message_id)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_key = get_emoji_key(payload.emoji)

    reaction_signups[payload.message_id][emoji_key].discard(user.name)
    if not reaction_signups[payload.message_id][emoji_key]:
        del reaction_signups[payload.message_id][emoji_key]

    thread = reaction_threads.get(payload.message_id)
    if not thread:
        thread = await get_or_create_thread(log_channel, message, payload.message_id)
        reaction_threads[payload.message_id] = thread
    await thread.send(log_line(user, payload.emoji, "removed"))

    await update_summary(log_channel, message, payload.message_id)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
