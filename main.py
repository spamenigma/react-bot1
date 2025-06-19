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
    718534017082720339: ("Support", 0xFFA500),
    1025015433054662676: ("CSW", 0xADD8E6),
    1091115981788684318: ("Renegade", 0x00FF00),
    1025067188102643853: ("Trident", 0x0000FF),
    1025067230347661412: ("Athena", 0x800080),
    792085274149519420: ("Pathfinder", None),
    663134181089607727: ("Not attending", None),
    123456789012345678: ("Late", None),
}

TIMESTAMP_F_RE = re.compile(r"<t:(\d+):F>")

# NEW: Regex to match ANY form of mention/ping (Discord formatted or literal @/#)
# when checking if an ENTIRE line should be skipped.
FULL_LINE_MENTION_RE = re.compile(r"^(?:<[@#]!?\d+>|@[a-zA-Z0-9_]+|#[a-zA-Z0-9_]+)\s*$", re.IGNORECASE)

# NEW: Regex to match ONLY Discord's internal mention format for cleaning within a string.
# This prevents removing literal '@' if it's part of a phrase like "attend @ the park"
DISCORD_FORMAT_MENTION_RE = re.compile(r"<[@#]!?(\d+)>")

def extract_title_and_timestamp(content: str):
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    title_line_index = 0
    while title_line_index < len(lines):
        current_line = lines[title_line_index]
        # Use FULL_LINE_MENTION_RE to check if the entire line is a mention/ping
        if FULL_LINE_MENTION_RE.fullmatch(current_line):
            title_line_index += 1
        else:
            break # Found a suitable title line

    title = "Sign-Ups" # Default title if no suitable line is found
    if title_line_index < len(lines):
        # Use DISCORD_FORMAT_MENTION_RE to remove only Discord's internal mention formats
        # from the chosen title line, leaving literal '@' or '#' if they are not part of a mention
        title = DISCORD_FORMAT_MENTION_RE.sub("", lines[title_line_index]).strip()
        # If after removing mentions, the line is empty, default to "Sign-Ups"
        if not title:
            title = "Sign-Ups"
    
    timestamp_str = ""
    match = TIMESTAMP_F_RE.search(content)
    if match:
        ts = int(match.group(1))
        dt = datetime.fromtimestamp(ts)
        timestamp_str = dt.strftime("%A, %d %B %Y %H:%M UTC")
    return title, timestamp_str

def emoji_display_and_label(emoji_obj):
    if hasattr(emoji_obj, "id") and emoji_obj.id in EMOJI_MAP:
        label, color = EMOJI_MAP[emoji_obj.id]
        return label, color
    name = str(emoji_obj)
    if name == "⏳":
        return "Late", None
    if name == "❌" or name == "🚫":
        return "Not attending", None
    return name, None

def build_summary_text(message_id, title, timestamp_str):
    emoji_data = reaction_signups[message_id]
    if not emoji_data:
        return "📋 No sign-ups yet."

    lines = []
    # No explicit replace('@', '') needed now as title should already be clean
    header = f"📋 **Sign-Ups for: {title}**"
    if timestamp_str:
        header += f"\n**When:** {timestamp_str}"
    lines.append(header)
    lines.append("-" * 30)

    for emoji_key, users in sorted(emoji_data.items()):
        if not users:
            continue
            
        label, color = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
        count = len(users)
        user_mentions = ', '.join(sorted(users))

        if label in ("Late", "Not attending"):
            header_line = f"{emoji_key} {count} {label}:"
        else:
            header_line = f"{emoji_key} {count} {label} attending:"
            
        lines.append(header_line)
        lines.append(f"> {user_mentions}")
        lines.append("")

    return "\n".join(lines)


async def get_or_create_thread_for_summary(summary_message: discord.Message, title: str):
    try:
        if summary_message.id in summary_threads:
            thread = summary_threads[summary_message.id]
            await bot.fetch_channel(thread.id)
            return thread, False
    except (discord.NotFound, AttributeError):
        summary_threads.pop(summary_message.id, None)

    thread = await summary_message.create_thread(
        name=f"Logs for {title}",
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
    return thread

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[`{time_str}`] **{user.display_name}** {action} reaction {emoji}"

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID or payload.member.bot:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel: return
    try:
        monitor_channel = guild.get_channel(payload.channel_id)
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception as e:
        print(f"Failed to fetch message on reaction add: {e}")
        return

    user = payload.member
    emoji_str = str(payload.emoji)
    reaction_signups[payload.message_id][emoji_str].add(user.display_name)

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
    if not guild: return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel: return
    try:
        monitor_channel = guild.get_channel(payload.channel_id)
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception as e:
        print(f"Failed to fetch message on reaction remove: {e}")
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    if not user or user.bot:
        return

    emoji_str = str(payload.emoji)
    
    if user.display_name in reaction_signups[payload.message_id][emoji_str]:
        reaction_signups[payload.message_id][emoji_str].remove(user.display_name)
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
