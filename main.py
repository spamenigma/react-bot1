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
LOG_CHANNEL_ID = 1384854378820800675      # Where logs and summaries go

# Special emojis to match by ID or unicode
CROSS_EMOJI_ID = "cross~1"  # Use the exact ID string from your bot's logs if possible
LATE_EMOJI_UNICODE = "⏳"

# Store sign-ups per emoji per message
reaction_signups = defaultdict(lambda: defaultdict(set))
# Keep track of summary message IDs per message to edit summaries instead of posting new
summary_messages = {}
# Keep track of threads per message to avoid recreating threads and reposting links
message_threads = {}

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

async def get_or_create_thread(log_channel: discord.TextChannel, message: discord.Message):
    # Parse the message content to find thread title
    lines = [line.strip() for line in message.content.splitlines()]
    title_line = ""
    if lines:
        if lines[0].startswith("@"):
            for line in lines[1:]:
                if line:
                    title_line = line
                    break
        else:
            title_line = lines[0]

    if not title_line:
        title_line = f"Message {message.id}"

    thread_name = f"Reactions for msg {message.id}: {title_line[:50]}"

    # Check for existing thread
    active_threads = [thread for thread in log_channel.threads if not thread.archived]
    for thread in active_threads:
        if thread.name == thread_name:
            return thread, False

    # Create new thread
    thread = await log_channel.create_thread(
        name=thread_name,
        auto_archive_duration=1440
    )
    return thread, True

def post_summary_line(emoji: str, users: set[str]) -> str:
    count = len(users)
    if emoji == CROSS_EMOJI_ID:
        return f"❌ **{count} not attending**"
    if emoji == LATE_EMOJI_UNICODE:
        plural = "s" if count > 1 else ""
        return f"⏳ **{count} late{plural}**"
    plural = "s" if count > 1 else ""
    return f"{emoji} **{count} signed up{plural}:**"

async def post_summary(log_channel: discord.TextChannel, message_id: int):
    table_lines = ["📋 **Sign-up Summary**"]
    emoji_data = reaction_signups[message_id]
    for emoji, users in emoji_data.items():
        if users:
            table_lines.append(post_summary_line(emoji, users))
            for user in sorted(users):
                table_lines.append(f"- {user}")
            table_lines.append("")

    content = "\n".join(table_lines) if len(table_lines) > 1 else "No sign-ups yet."

    summary_msg_id = summary_messages.get(message_id)
    if summary_msg_id:
        try:
            msg = await log_channel.fetch_message(summary_msg_id)
            await msg.edit(content=content)
        except (discord.NotFound, discord.Forbidden):
            new_msg = await log_channel.send(content)
            summary_messages[message_id] = new_msg.id
    else:
        new_msg = await log_channel.send(content)
        summary_messages[message_id] = new_msg.id

async def link_thread_message(log_channel: discord.TextChannel, thread: discord.Thread, thread_created: bool):
    if thread_created:
        # Send a message in the logs channel linking to the new thread
        link_msg = (
            f"🧵 **Thread created:** [{thread.name}]({thread.jump_url})"
        )
        await log_channel.send(link_msg)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    try:
        monitored_channel = guild.get_channel(payload.channel_id)
        message = await monitored_channel.fetch_message(payload.message_id)
    except Exception:
        return

    # Get or create thread once per message
    if payload.message_id in message_threads:
        thread = message_threads[payload.message_id]
        thread_created = False
    else:
        thread, thread_created = await get_or_create_thread(log_channel, message)
        message_threads[payload.message_id] = thread
        # Post link message if thread just created
        await link_thread_message(log_channel, thread, thread_created)

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_str = str(payload.emoji)

    # Track reaction signups
    reaction_signups[payload.message_id][emoji_str].add(user.name)

    await thread.send(log_line(user, payload.emoji, "added"))
    await post_summary(log_channel, payload.message_id)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    try:
        monitored_channel = guild.get_channel(payload.channel_id)
        message = await monitored_channel.fetch_message(payload.message_id)
    except Exception:
        return

    if payload.message_id in message_threads:
        thread = message_threads[payload.message_id]
        thread_created = False
    else:
        thread, thread_created = await get_or_create_thread(log_channel, message)
        message_threads[payload.message_id] = thread
        await link_thread_message(log_channel, thread, thread_created)

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_str = str(payload.emoji)

    # Remove reaction signup
    if user.name in reaction_signups[payload.message_id][emoji_str]:
        reaction_signups[payload.message_id][emoji_str].remove(user.name)
        if not reaction_signups[payload.message_id][emoji_str]:
            del reaction_signups[payload.message_id][emoji_str]

    await thread.send(log_line(user, payload.emoji, "removed"))
    await post_summary(log_channel, payload.message_id)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
