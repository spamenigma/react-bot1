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

reaction_signups = defaultdict(lambda: defaultdict(set))
message_threads = {}
message_link_sent = set()
summary_message_ids = {}  # message_id: summary_message_id in log channel

EMOJI_LABELS = {
    718534017082720339: "Support",
    1025015433054662676: "CSW signed up",
    1091115981788684318: "Renegade signed up",
    1025067188102643853: "Trident signed up",
    1025067230347661412: "Athena signed up",
    792085274149519420: "Pathfinder signed up",
    "🏴‍☠️": "OPFOR signed up",
}

def format_action_label(emoji_key, count):
    if emoji_key == "⏳":
        return f"{count} late"
    label = EMOJI_LABELS.get(emoji_key, None)
    if label:
        return f"{count} {label}"
    if isinstance(emoji_key, int):
        return f"{count} emoji id {emoji_key} signed up"
    return f"{count} {emoji_key} signed up"

async def get_or_create_thread(log_channel: discord.TextChannel, message: discord.Message):
    thread = message_threads.get(message.id)
    if thread and not thread.archived:
        return thread

    active_threads = [t for t in log_channel.threads if not t.archived]

    title_lines = [line.strip() for line in message.content.splitlines() if line.strip()]
    thread_name = None
    if title_lines:
        first_line = title_lines[0]
        if first_line.startswith("<@") or first_line.startswith("@"):
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

    for t in active_threads:
        if t.name == thread_name:
            message_threads[message.id] = t
            return t

    thread = await log_channel.create_thread(
        name=thread_name,
        auto_archive_duration=1440,
    )
    message_threads[message.id] = thread
    return thread

def log_line(user: discord.User, emoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    emoji_str = str(emoji)
    return f"[{time_str}] {user} {action} reaction {emoji_str}"

async def post_summary(log_channel, message_id):
    emoji_data = reaction_signups.get(message_id)
    if not emoji_data:
        return

    lines = ["📋 **Sign-up Summary**"]
    for emoji_key, users in emoji_data.items():
        if users:
            count = len(users)
            line = format_action_label(emoji_key, count)
            lines.append(line)
            for user in sorted(users):
                lines.append(f"- {user}")
            lines.append("")

    if len(lines) > 1:
        # Delete old summary message if exists
        old_summary_id = summary_message_ids.get(message_id)
        if old_summary_id:
            try:
                old_msg = await log_channel.fetch_message(old_summary_id)
                await old_msg.delete()
            except Exception:
                pass

        msg = await log_channel.send("\n".join(lines))
        summary_message_ids[message_id] = msg.id

async def post_link_message(log_channel, message: discord.Message, thread: discord.Thread):
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
    emoji_key = emoji_obj.id if (hasattr(emoji_obj, "id") and emoji_obj.id) else str(emoji_obj)

    reaction_signups[payload.message_id][emoji_key].add(user.name)

    await thread.send(log_line(user, emoji_obj, "added"))
    await post_summary(log_channel, payload.message_id)
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

    if user.name in reaction_signups[payload.message_id][emoji_key]:
        reaction_signups[payload.message_id][emoji_key].remove(user.name)
        if not reaction_signups[payload.message_id][emoji_key]:
            del reaction_signups[payload.message_id][emoji_key]

    await thread.send(log_line(user, emoji_obj, "removed"))
    await post_summary(log_channel, payload.message_id)
    await post_link_message(log_channel, message, thread)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
