import os
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
import re

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

MONITOR_CHANNEL_ID = 1384853874967449640
LOG_CHANNEL_ID = 1384854378820800675

reaction_signups = defaultdict(lambda: defaultdict(set))
summary_messages = {}
summary_threads = {}

EMOJI_INFO = {
    718534017082720339: ("Support", 0xFFA500, "🧡"),
    1025015433054662676: ("CSW signed up", 0xADD8E6, "💙"),
    1091115981788684318: ("Renegade signed up", 0x800080, "💜"),
    1025067188102643853: ("Trident signed up", 0x0000FF, "🔱"),
    1025067230347661412: ("Athena signed up", 0x008080, "♈"),
    792085274149519420: ("Pathfinder signed up", 0x228B22, "🏹"),
    663134181089607727: ("Carrier Star Wing", 0xFFD700, "✈️"),
}

NOT_ATTENDING_EMOJI_ID = 718534017082720339
LATE_EMOJI = "⏳"

def extract_title_and_timestamp(message_content):
    lines = [line.strip() for line in message_content.splitlines() if line.strip()]
    if not lines:
        return "No Title", None
    if lines[0].startswith("<@") or lines[0].startswith("@"):
        title_line = None
        for line in lines[1:]:
            if line:
                title_line = line
                break
        if not title_line:
            title_line = lines[0]
    else:
        title_line = lines[0]

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

    sorted_emojis = sorted(emoji_data.items(), key=lambda e: (
        e[0] == str(LATE_EMOJI),
        e[0] == str(NOT_ATTENDING_EMOJI_ID),
        e[0]
    ))

    for emoji_str, users in sorted_emojis:
        if not users:
            continue
        count = len(users)
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
            display_text = f"{count} {emoji_str} attending"

        user_list = ", ".join(sorted(users))
        lines.append(f"{display_text}: {user_list}")

    return "\n".join(lines)

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

async def get_or_create_thread_for_summary(summary_message: discord.Message, title: str):
    if summary_message.id in summary_threads:
        thread = summary_threads[summary_message.id]
        try:
            await thread.fetch()
            return thread, False
        except discord.NotFound:
            del summary_threads[summary_message.id]

    thread = await summary_message.create_thread(
        name=f"Reactions for {title}",
        auto_archive_duration=1440
    )
    summary_threads[summary_message.id] = thread
    return thread, True

async def post_or_edit_summary_and_get_thread(log_channel, message_id, title, timestamp_str):
    summary_text = build_summary_text(message_id, title, timestamp_str)
    if message_id in summary_messages:
        try:
            summary_message = summary_messages[message_id]
            await summary_message.edit(content=summary_text)
        except discord.NotFound:
            summary_message = await log_channel.send(summary_text)
            summary_messages[message_id] = summary_message
    else:
        summary_message = await log_channel.send(summary_text)
        summary_messages[message_id] = summary_message

    thread, created = await get_or_create_thread_for_summary(summary_message, title)
    return thread

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        return
    try:
        monitor_channel = guild.get_channel(payload.channel_id)
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)

    reaction_signups[payload.message_id][emoji].add(user.name)

    title, timestamp_str = extract_title_and_timestamp(message.content)

    thread = await post_or_edit_summary_and_get_thread(log_channel, payload.message_id, title, timestamp_str)

    await thread.send(log_line(user, emoji, "added"))

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        return
    try:
        monitor_channel = guild.get_channel(payload.channel_id)
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)

    if user.name in reaction_signups[payload.message_id][emoji]:
        reaction_signups[payload.message_id][emoji].remove(user.name)
        if not reaction_signups[payload.message_id][emoji]:
            del reaction_signups[payload.message_id][emoji]

    title, timestamp_str = extract_title_and_timestamp(message.content)

    thread = await post_or_edit_summary_and_get_thread(log_channel, payload.message_id, title, timestamp_str)

    await thread.send(log_line(user, emoji, "removed"))


if __name__ == "__main__":
    # Comment this out if you don't have keep_alive implemented
    # from keep_alive import keep_alive
    # keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
