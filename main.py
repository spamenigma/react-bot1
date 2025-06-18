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
summary_messages = {}  # message_id -> summary message in log channel

EMOJI_LABELS = {
    718534017082720339: "Not attending",
    1025015433054662676: ":Carrier_Star_Wing: CSW",
    1091115981788684318: ":Renegade: Renegade",
    1025067188102643853: ":Trident: Trident",
    1025067230347661412: ":Athena_Training_SQN: Athena",
    792085274149519420: ":pathfinders: Pathfinder",
    "🏴‍☠️": ":pirate_flag: OPFOR",
    "⏳": "Late",
}

COLOR_LABELS = {
    1025015433054662676: "🟧",  # CSW (orange)
    1025067188102643853: "🔷",  # Trident (blue)
    1025067230347661412: "🟦",  # Athena (light blue)
}

def extract_title_and_time(message):
    lines = message.content.splitlines()
    title = ""
    timestamp = ""
    for line in lines:
        if line.strip() and not line.strip().startswith("<@"):
            if not title:
                title = line.strip()
            elif not timestamp and ("<t:" in line):
                timestamp = line.strip()
    return title, timestamp

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

async def get_or_create_thread(log_channel: discord.TextChannel, message_id: int, title: str):
    for thread in log_channel.threads:
        if thread.name.startswith(f"Reactions for msg {message_id}"):
            return thread
    thread = await log_channel.create_thread(
        name=f"Reactions for msg {message_id} — {title[:50]}",
        auto_archive_duration=1440
    )
    await log_channel.send(f"🧵 Created thread for **{title}** → {thread.mention}")
    return thread

def get_label(emoji):
    if hasattr(emoji, "id") and emoji.id:
        label = EMOJI_LABELS.get(emoji.id)
        color = COLOR_LABELS.get(emoji.id, "")
        return f"{color} {label}" if label else f"<:{emoji.name}:{emoji.id}>"
    else:
        return EMOJI_LABELS.get(str(emoji), str(emoji))

async def post_or_update_summary(log_channel, original_msg, message_id):
    title, time_line = extract_title_and_time(original_msg)
    summary_lines = [f"📋 **Sign-Ups for {title} {time_line}**"]
    emoji_data = reaction_signups[message_id]
    for emoji, users in emoji_data.items():
        if not users:
            continue
        label = get_label(discord.PartialEmoji(name=emoji))
        label = label or emoji
        prefix = f"**{len(users)} {label} attending:**" if label not in ["Not attending", "Late"] else f"**{len(users)} {label}:**"
        line = f"{prefix} {', '.join(sorted(users))}"
        summary_lines.append(line)
    content = "\n".join(summary_lines)

    if message_id in summary_messages:
        try:
            msg = await log_channel.fetch_message(summary_messages[message_id])
            await msg.edit(content=content)
        except discord.NotFound:
            summary_msg = await log_channel.send(content)
            summary_messages[message_id] = summary_msg.id
    else:
        summary_msg = await log_channel.send(content)
        summary_messages[message_id] = summary_msg.id

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    thread_title, _ = extract_title_and_time(message)
    thread = await get_or_create_thread(log_channel, message.id, thread_title)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)
    reaction_signups[payload.message_id][emoji].add(user.name)
    await thread.send(log_line(user, payload.emoji, "added"))
    await post_or_update_summary(log_channel, message, payload.message_id)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    thread_title, _ = extract_title_and_time(message)
    thread = await get_or_create_thread(log_channel, message.id, thread_title)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)
    if user.name in reaction_signups[payload.message_id][emoji]:
        reaction_signups[payload.message_id][emoji].remove(user.name)
        if not reaction_signups[payload.message_id][emoji]:
            del reaction_signups[payload.message_id][emoji]
    await thread.send(log_line(user, payload.emoji, "removed"))
    await post_or_update_summary(log_channel, message, payload.message_id)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
