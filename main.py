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
LOG_CHANNEL_ID = 1384854378820800675      # Where threads and logs go

# Custom emoji IDs and labels
EMOJI_LABELS = {
    1025015433054662676: (":Carrier_Star_Wing:", "CSW", 0x00bfff),
    1025067188102643853: (":Trident:", "Trident", 0x0000ff),
    1025067230347661412: (":Athena_Training_SQN:", "Athena", 0x008080),
    1091115981788684318: (":Renegade:", "Renegade", 0x800080),
    792085274149519420: (":Pathfinder:", "Pathfinder", 0x808000),
    663134181089607727: (":OPFOR:", "OPFOR", 0x808080),
    718534017082720339: ("❌", "Not attending", 0xff0000),
    0x23f3: ("⏳", "Late", 0xffa500),  # Unicode clock emoji
    0x1f198: ("🆘", "Support", 0xff8800),
}

reaction_signups = defaultdict(lambda: defaultdict(set))
threads_by_message = {}


def extract_title_and_timestamp(message):
    lines = message.content.splitlines()
    title = ""
    for line in lines:
        if not line.strip():
            continue
        if line.strip().startswith("<@"):
            continue
        title = line.strip()
        break

    timestamp_match = re.search(r'<t:(\d+):[tTdDfFR]?>', message.content)
    if timestamp_match:
        dt = datetime.utcfromtimestamp(int(timestamp_match.group(1)))
        return f"{title} {dt.strftime('%A, %d %B %Y %H:%M')}", title
    return title, title


async def get_or_create_thread(log_channel, message):
    thread = threads_by_message.get(message.id)
    if thread and not thread.archived:
        return thread

    for t in log_channel.threads:
        if t.name.startswith(f"Reactions for msg {message.id}"):
            threads_by_message[message.id] = t
            return t

    title, _ = extract_title_and_timestamp(message)
    thread = await log_channel.create_thread(name=f"Reactions for msg {message.id}: {title}", auto_archive_duration=1440)
    threads_by_message[message.id] = thread

    await log_channel.send(f"📌 Created thread for **{title}** → {thread.mention}")
    return thread


def log_line(user, emoji_str, action):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji_str}"


def summarize_signups(message_id, message_title):
    lines = [f"\n📋 Sign-Ups for {message_title}"]
    emoji_data = reaction_signups[message_id]

    for emoji, users in emoji_data.items():
        if not users:
            continue

        label = emoji
        user_list = ", ".join(sorted(users))

        for eid, (symbol, name, _) in EMOJI_LABELS.items():
            if str(emoji) == symbol or (emoji.startswith(":") and eid in emoji):
                label = f"{name}"
                break

        count = len(users)
        if label == "Late":
            lines.append(f"{count} Late: {user_list}")
        elif label == "Not attending":
            lines.append(f"{count} Not attending: {user_list}")
        else:
            lines.append(f"{count} {label} attending: {user_list}")

    return "\n".join(lines)


@bot.event
async def on_raw_reaction_add(payload):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    thread = await get_or_create_thread(log_channel, message)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_str = str(payload.emoji)

    reaction_signups[payload.message_id][emoji_str].add(user.name)
    await thread.send(log_line(user, emoji_str, "added"))

    summary_title, _ = extract_title_and_timestamp(message)
    summary = summarize_signups(payload.message_id, summary_title)
    await log_channel.send(summary)


@bot.event
async def on_raw_reaction_remove(payload):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    thread = await get_or_create_thread(log_channel, message)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_str = str(payload.emoji)

    if user.name in reaction_signups[payload.message_id][emoji_str]:
        reaction_signups[payload.message_id][emoji_str].remove(user.name)
        if not reaction_signups[payload.message_id][emoji_str]:
            del reaction_signups[payload.message_id][emoji_str]

    await thread.send(log_line(user, emoji_str, "removed"))

    summary_title, _ = extract_title_and_timestamp(message)
    summary = summarize_signups(payload.message_id, summary_title)
    await log_channel.send(summary)


if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
