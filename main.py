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

# Constants for custom emoji IDs
EMOJI_LABELS = {
    718534017082720339: ("❌", "Not attending"),
    1025015433054662676: ("<:CSW:1025015433054662676>", "CSW"),
    1091115981788684318: ("<:Renegade:1091115981788684318>", "Renegade"),
    1025067188102643853: ("<:Trident:1025067188102643853>", "Trident"),
    1025067230347661412: ("<:Athena:1025067230347661412>", "Athena"),
    792085274149519420: ("<:Pathfinder:792085274149519420>", "Pathfinder"),
    663134181089607727: ("<:Support:663134181089607727>", "Support"),
    "⏳": ("⏳", "Late"),
    "🏴‍☠️": ("🏴‍☠️", "OPFOR"),
}

# Store sign-ups per emoji per message
reaction_signups = defaultdict(lambda: defaultdict(set))
message_threads = {}  # message_id -> thread
signup_messages = {}  # message_id -> summary message

async def get_or_create_thread(log_channel: discord.TextChannel, message_id: int, title: str):
    if message_id in message_threads:
        thread = await log_channel.fetch_thread(message_threads[message_id])
        if thread and not thread.archived:
            return thread

    active_threads = [thread for thread in log_channel.threads if not thread.archived]
    for thread in active_threads:
        if thread.name.startswith(f"Reactions for msg {message_id}"):
            message_threads[message_id] = thread.id
            return thread

    thread = await log_channel.create_thread(
        name=f"Reactions for msg {message_id}: {title[:50]}",
        auto_archive_duration=1440
    )
    message_threads[message_id] = thread.id
    return thread

def log_line(user: discord.User, emoji_obj, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    emoji_str = get_emoji_str(emoji_obj)
    return f"[{time_str}] {user} {action} reaction {emoji_str}"

def get_emoji_str(emoji):
    if hasattr(emoji, "id") and emoji.id in EMOJI_LABELS:
        return EMOJI_LABELS[emoji.id][0]
    return str(emoji)

def get_label(emoji):
    if hasattr(emoji, "id") and emoji.id in EMOJI_LABELS:
        return EMOJI_LABELS[emoji.id][1]
    if isinstance(emoji, str) and emoji in EMOJI_LABELS:
        return EMOJI_LABELS[emoji][1]
    return f"{emoji}"

def extract_title_and_time(message: discord.Message):
    lines = message.content.splitlines()
    lines = [line.strip() for line in lines if line.strip() and not line.startswith("<@")]
    title = lines[0] if lines else "Event"
    timestamp = next((word for word in message.content.split() if word.startswith("<t:") and word.endswith(">")), None)
    return title, timestamp

async def post_summary(log_channel, message_id, title, timestamp):
    summary_lines = [f"📋 **Sign-Ups for {title} {timestamp or ''}**\n"]
    emoji_data = reaction_signups[message_id]
    for emoji_key, users in emoji_data.items():
        if not users:
            continue
        label = get_label(emoji_key)
        count = len(users)
        label_line = f"**{count} {label}**:" if label not in ["Not attending", "Late"] else f"**{count} {label}**"
        summary_lines.append(label_line)
        if label not in ["Not attending", "Late"]:
            for user in sorted(users):
                summary_lines.append(f"- {user}")
        summary_lines.append("")

    summary_text = "\n".join(summary_lines)

    # Update or create summary
    if message_id in signup_messages:
        try:
            prev_msg = await log_channel.fetch_message(signup_messages[message_id])
            await prev_msg.edit(content=summary_text)
            return
        except Exception:
            pass

    msg = await log_channel.send(summary_text)
    signup_messages[message_id] = msg.id

async def handle_reaction(payload, action):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    channel = guild.get_channel(payload.channel_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)

    try:
        message = await channel.fetch_message(payload.message_id)
    except Exception:
        return

    title, timestamp = extract_title_and_time(message)
    thread = await get_or_create_thread(log_channel, message.id, title)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji

    key = emoji.id if emoji.id else str(emoji)

    if action == "add":
        reaction_signups[payload.message_id][key].add(user.name)
    elif action == "remove":
        reaction_signups[payload.message_id][key].discard(user.name)
        if not reaction_signups[payload.message_id][key]:
            del reaction_signups[payload.message_id][key]

    await thread.send(log_line(user, emoji, action))
    await post_summary(log_channel, payload.message_id, title, timestamp)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await handle_reaction(payload, "add")

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await handle_reaction(payload, "remove")

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
