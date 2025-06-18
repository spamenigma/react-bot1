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
LOG_CHANNEL_ID = 1384854378820800675      # Where threads and logs go

# Store sign-ups per emoji per message
reaction_signups = defaultdict(lambda: defaultdict(set))
# Track threads per message
message_threads = {}
# Track if link message sent for a message_id
message_link_sent = set()

# Emoji ID and Unicode to label mapping
EMOJI_LABELS = {
    718534017082720339: "Support",
    1025015433054662676: "CSW signed up",
    1091115981788684318: "Renegade signed up",
    1025067188102643853: "Trident signed up",
    1025067230347661412: "Athena signed up",
    792085274149519420: "Pathfinder signed up",
    "🏴‍☠️": "OPFOR signed up",
    # Add any others you want here
}

def format_action_label(emoji_key, count):
    if emoji_key == "⏳":
        return f"{count} late"
    label = EMOJI_LABELS.get(emoji_key, None)
    if label:
        return f"{count} {label}"
    # fallback to showing emoji + text
    if isinstance(emoji_key, int):
        return f"{count} emoji id {emoji_key} signed up"
    return f"{count} {emoji_key} signed up"

async def get_or_create_thread(log_channel: discord.TextChannel, message: discord.Message):
    # Use cached thread if exists
    thread = message_threads.get(message.id)
    if thread and not thread.archived:
        return thread

    # Find existing thread by name
    active_threads = [t for t in log_channel.threads if not t.archived]
    # Determine thread name from message first or second line (skip @mentions)
    title_lines = [line.strip() for line in message.content.splitlines() if line.strip()]
    thread_name = None
    if title_lines:
        # If first line is @mention(s), use second non-empty non-mention line if exists
        first_line = title_lines[0]
        if first_line.startswith("<@") or first_line.startswith("@"):
            # Look for next line not starting with @ or blank
            for line in title_lines[1:]:
                if not line.startswith("<@") and not line.startswith("@"):
                    thread_name = line
                    break
            if not thread_name and len(title_lines) > 1:
                thread_name = title_lines[1]
        else:
            thread_name = first_line
    if not thread_name:
        thread_name = f"Reactions for msg {message.id}"

    # Try to find thread by this name
    for t in active_threads:
        if t.name == thread_name:
            message_threads[message.id] = t
            return t

    # Create new thread
    thread = await log_channel.create_thread(
        name=thread_name,
        auto_archive_duration=1440,
        # Optionally, you can set the message this thread belongs to:
        # message=message
    )
    message_threads[message.id] = thread
    return thread

def log_line(user: discord.User, emoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    # Show emoji as str: custom emoji or unicode
    if hasattr(emoji, "id") and emoji.id:
        emoji_str = str(emoji)
    else:
        emoji_str = emoji if isinstance(emoji, str) else str(emoji)
    return f"[{time_str}] {user} {action} reaction {emoji_str}"

async def post_summary(log_channel, thread, message_id):
    emoji_data = reaction_signups.get(message_id)
    if not emoji_data:
        return

    lines = ["\n📋 **Sign-up Summary**"]
    for emoji_key, users in emoji_data.items():
        if users:
            count = len(users)
            line = format_action_label(emoji_key, count)
            lines.append(line)
            for user in sorted(users):
                lines.append(f"- {user}")
            lines.append("")

    if len(lines) > 1:
        # Delete old bot messages with "Sign-up Summary" in thread to keep it clean
        async for msg in thread.history(limit=50):
            if msg.author == bot.user and msg.content.startswith("\n📋 **Sign-up Summary**"):
                await msg.delete()
        await thread.send("\n".join(lines))

async def post_link_message(log_channel, message: discord.Message, thread: discord.Thread):
    # Only post once per message ID
    if message.id in message_link_sent:
        return
    link = f"https://discord.com/channels/{message.guild.id}/{log_channel.id}/{thread.id}"
    await log_channel.send(f"🔗 Summary thread for message **{thread.name}**: {link}")
    message_link_sent.add(message.id)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    monitor_channel = guild.get_channel(payload.channel_id)
    if not log_channel or not monitor_channel:
        return

    try:
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return

    thread = await get_or_create_thread(log_channel, message)

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)

    emoji_obj = payload.emoji
    # Use emoji ID if custom emoji, else string emoji for unicode
    emoji_key = emoji_obj.id if (hasattr(emoji_obj, "id") and emoji_obj.id) else str(emoji_obj)

    # Track reaction
    reaction_signups[payload.message_id][emoji_key].add(user.name)

    await thread.send(log_line(user, emoji_obj, "added"))
    await post_summary(log_channel, thread, payload.message_id)
    await post_link_message(log_channel, message, thread)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    monitor_channel = guild.get_channel(payload.channel_id)
    if not log_channel or not monitor_channel:
        return

    try:
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return

    thread = await get_or_create_thread(log_channel, message)

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)

    emoji_obj = payload.emoji
    emoji_key = emoji_obj.id if (hasattr(emoji_obj, "id") and emoji_obj.id) else str(emoji_obj)

    # Remove reaction
    if user.name in reaction_signups[payload.message_id][emoji_key]:
        reaction_signups[payload.message_id][emoji_key].remove(user.name)
        if not reaction_signups[payload.message_id][emoji_key]:
            del reaction_signups[payload.message_id][emoji_key]

    await thread.send(log_line(user, emoji_obj, "removed"))
    await post_summary(log_channel, thread, payload.message_id)
    await post_link_message(log_channel, message, thread)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
