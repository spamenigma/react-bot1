import os
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
import re
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

MONITOR_CHANNEL_ID = 1384853874967449640  # Where reactions happen
LOG_CHANNEL_ID = 1384854378820800675      # Where logs & threads go

# Store sign-ups per emoji per message
reaction_signups = defaultdict(lambda: defaultdict(set))

# Cache summary messages and threads per monitored message
summary_messages = {}
summary_threads = {}

# Emoji ID mappings for wording and emoji display
EMOJI_MAP = {
    718534017082720339: ("🧡 Support", 0xFFA500),               # Support orange
    1025015433054662676: ("💙 CSW", 0xADD8E6),                 # CSW light blue
    1091115981788684318: ("💚 Renegade", 0x00FF00),
    1025067188102643853: ("💙 Trident", 0x0000FF),             # Trident blue
    1025067230347661412: ("💜 Athena", 0x800080),
    792085274149519420: ("🏹 Pathfinder", None),               # Use emoji, no color
    663134181089607727: ("🚫 Not attending", None),            # Cross emoji ID
    123456789012345678: ("⏳ Late", None),                      # Placeholder Late emoji ID
}

LATE_EMOJI_IDS = {123456789012345678}  # Replace with actual Late emoji IDs
NOT_ATTENDING_IDS = {663134181089607727}  # Replace with actual cross emoji IDs

TIMESTAMP_F_RE = re.compile(r"<t:(\d+):F>")  # Match Discord :F timestamps
PING_RE = re.compile(r"^<@!?(\d+)>$")

def extract_title_and_timestamp(content: str):
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    # Skip first line if it’s a ping (@)
    if lines and PING_RE.match(lines[0]):
        lines = lines[1:]
    title = lines[0] if lines else "Sign-Ups"
    timestamp_str = ""

    # Try to find first :F timestamp anywhere in content
    match = TIMESTAMP_F_RE.search(content)
    if match:
        ts = int(match.group(1))
        dt = datetime.utcfromtimestamp(ts)
        timestamp_str = dt.strftime("%A, %d %B %Y %H:%M UTC")
    return title, timestamp_str

def emoji_display_and_label(emoji_obj):
    # Match by ID first if possible
    if hasattr(emoji_obj, "id") and emoji_obj.id in EMOJI_MAP:
        label, color = EMOJI_MAP[emoji_obj.id]
        return label, color
    # Fall back to unicode or name string
    name = str(emoji_obj)
    # Special case Late and Not attending emojis by name if needed here
    if name == "⏳":
        return "⏳ Late", None
    if name == "❌" or name == ":cross~1:":
        return "🚫 Not attending", None
    # Default label is emoji itself, no color
    return name, None

def build_summary_text(message_id, title, timestamp_str):
    emoji_data = reaction_signups[message_id]
    if not emoji_data:
        return "📋 No sign-ups yet."

    lines = []
    header = f"📋 Sign-Ups for {title}"
    if timestamp_str:
        header += f" {timestamp_str}"
    lines.append(header)

    for emoji_key, users in emoji_data.items():
        if not users:
            continue
        label, color = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
        count = len(users)
        # Format line, for "Late" show differently
        if "Late" in label:
            line = f"{count} Late: {', '.join(sorted(users))}"
        elif "Not attending" in label:
            line = f"{count} Not attending: {', '.join(sorted(users))}"
        else:
            line = f"{count} {label} attending: {', '.join(sorted(users))}"
        lines.append(line)

    return "\n".join(lines)

async def get_or_create_thread_for_summary(summary_message: discord.Message, title: str):
    try:
        if summary_message.id in summary_threads:
            thread = summary_threads[summary_message.id]
            # Confirm thread still exists
            await thread.fetch()
            return thread, False
    except (discord.NotFound, AttributeError):
        summary_threads.pop(summary_message.id, None)

    # Create new thread if missing or invalid
    thread = await summary_message.create_thread(
        name=f"Reactions for {title}",
        auto_archive_duration=1440
    )
    summary_threads[summary_message.id] = thread
    return thread, True

async def post_or_edit_summary_and_get_thread(log_channel, message_id, title, timestamp_str):
    summary_text = build_summary_text(message_id, title, timestamp_str)
    summary_message = None

    if message_id in summary_messages:
        try:
            summary_message = summary_messages[message_id]
            await summary_message.edit(content=summary_text)
        except discord.NotFound:
            summary_messages.pop(message_id, None)

    if summary_message is None:
        summary_message = await log_channel.send(summary_text)
        summary_messages[message_id] = summary_message

    thread, created = await get_or_create_thread_for_summary(summary_message, title)

    # If just created, post a link message in logs channel
    if created:
        try:
            link_msg = await log_channel.send(f"Created thread for {title} → {thread.mention}")
            # Optionally store or pin link_msg if needed
        except Exception as e:
            print(f"Failed to send thread link message: {e}")

    return thread

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

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
    emoji_str = str(payload.emoji)

    # Track sign-up
    reaction_signups[payload.message_id][emoji_str].add(user.name)

    title, timestamp_str = extract_title_and_timestamp(message.content)
    thread = await post_or_edit_summary_and_get_thread(log_channel, payload.message_id, title, timestamp_str)

    try:
        await thread.send(log_line(user, payload.emoji, "added"))
    except Exception as e:
        print(f"Failed to send add log in thread: {e}")

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
    emoji_str = str(payload.emoji)

    # Remove sign-up
    if user.name in reaction_signups[payload.message_id][emoji_str]:
        reaction_signups[payload.message_id][emoji_str].remove(user.name)
        if not reaction_signups[payload.message_id][emoji_str]:
            del reaction_signups[payload.message_id][emoji_str]

    title, timestamp_str = extract_title_and_timestamp(message.content)
    thread = await post_or_edit_summary_and_get_thread(log_channel, payload.message_id, title, timestamp_str)

    try:
        await thread.send(log_line(user, payload.emoji, "removed"))
    except Exception as e:
        print(f"Failed to send remove log in thread: {e}")

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
