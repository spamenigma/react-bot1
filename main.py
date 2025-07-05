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
    1025015433054662676: ("Carrier Star Wing", None),
    718534017082720339: ("Squadron 1", None),
    663133357592412181: ("Attending", None),
    1025067230347661412: ("Athena Training", None),
    663134181089607727: ("Not attending", None),
    792085274149519420: ("Pathfinders", None),
    1025067188102643853: ("Trident", None),
    1091115981788684318: ("Renegade", None),
}

# Updated regex patterns
TIMESTAMP_F_RE = re.compile(r"<t:(\d+):F>")
PING_RE = re.compile(r"^<@!?(\d+)>$")
ROLE_MENTION_RE = re.compile(r"^<@&(\d+)>$")
MIXED_MENTIONS_RE = re.compile(r"^(<@[!&]?\d+>\s*)+$")

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Discord.py version: {discord.__version__}')
    
    # Check if UI is available
    try:
        test_view = discord.ui.View()
        print("✅ Discord UI components are available!")
    except AttributeError as e:
        print(f"❌ Discord UI components not available: {e}")
    
    await sync_recent_reactions()

# Basic test command that should always work
@bot.command(name="ping")
async def ping(ctx):
    """Simple test command"""
    await ctx.send("🏓 Pong! Bot is responding.")

# Simple button test
@bot.command(name="button_test")
async def button_test(ctx):
    """Test if buttons work at all"""
    try:
        print("Creating simple button test...")
        
        view = discord.ui.View(timeout=60)
        
        button = discord.ui.Button(
            label="Test Button", 
            style=discord.ButtonStyle.primary,
            custom_id="test_button_simple"
        )
        
        async def button_callback(interaction):
            await interaction.response.send_message("✅ Button works!", ephemeral=True)
        
        button.callback = button_callback
        view.add_item(button)
        
        await ctx.send("🔘 **Button Test** - Click the button below:", view=view)
        print("Button test sent!")
        
    except Exception as e:
        print(f"Button test error: {e}")
        await ctx.send(f"❌ Button test failed: {e}")

# Check discord version
@bot.command(name="version")
async def version_check(ctx):
    """Check discord.py version"""
    try:
        version = discord.__version__
        embed = discord.Embed(title="Version Info", color=0x00FF00)
        embed.add_field(name="Discord.py Version", value=version, inline=False)
        
        # Test UI availability
        try:
            discord.ui.View()
            ui_status = "✅ Available"
        except:
            ui_status = "❌ Not Available"
        
        embed.add_field(name="UI Components", value=ui_status, inline=False)
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Version check error: {e}")

def extract_title_and_timestamp(content: str):
    """Extract title and timestamp from message content."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    if not lines:
        return "Sign-Ups", ""
    
    title = None
    
    # Find the first line that isn't just mentions
    for line in lines:
        if MIXED_MENTIONS_RE.match(line) or PING_RE.match(line) or ROLE_MENTION_RE.match(line):
            continue
        title = line
        break
    
    if not title:
        title = "Sign-Ups"
    
    # Extract timestamp
    timestamp_str = ""
    match = TIMESTAMP_F_RE.search(content)
    if match:
        ts = int(match.group(1))
        dt = datetime.utcfromtimestamp(ts)
        timestamp_str = dt.strftime("%A, %d %B %Y %H:%M UTC")
    
    return title, timestamp_str

def emoji_display_and_label(emoji_obj):
    """Get display label for emoji"""
    if hasattr(emoji_obj, "id") and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
        clean_name, color = EMOJI_MAP[emoji_obj.id]
        emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
        return f"{emoji_display} {clean_name}", color
    
    name = str(emoji_obj)
    if name == "⏳":
        return "⏳ Late", None
    if (name == "❌" or name == ":cross~1:" or "cross" in name.lower() or 
        name == "<:cross:663134181089607727>" or ":cross:" in name):
        return "🚫 Not attending", None
    
    if hasattr(emoji_obj, 'name') and hasattr(emoji_obj, 'id') and emoji_obj.id:
        emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
        clean_name = emoji_obj.name.replace('_', ' ').title()
        return f"{emoji_display} {clean_name}", None
    
    return name, None

def build_summary_embed(message_id, title, timestamp_str):
    """Build a rich embed with names listed one per line under each reaction"""
    emoji_data = reaction_signups[message_id]
    
    if not emoji_data:
        embed = discord.Embed(
            title="📋 No sign-ups yet", 
            description="Be the first to react!",
            color=0x808080
        )
        return embed
    
    # Calculate unique attendees
    unique_attendees = set()
    for emoji_key, users in emoji_data.items():
        label, _ = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
        if "Not attending" not in label and "Late" not in label:
            unique_attendees.update(users)
    
    total_attending = len(unique_attendees)
    
    embed = discord.Embed(
        title=f"📋 {title}",
        description=f"**{total_attending}** total attending",
        color=0x00FF00
    )
    
    if timestamp_str:
        embed.add_field(
            name="⏰ Event Time", 
            value=f"```{timestamp_str}```", 
            inline=False
        )
    
    # Sort reactions
    attending_reactions = []
    other_reactions = []
    
    for emoji_key, users in emoji_data.items():
        if not users:
            continue
            
        label, color = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
        
        if "Not attending" in label or "Late" in label:
            other_reactions.append((emoji_key, users, label))
        else:
            attending_reactions.append((emoji_key, users, label))
    
    # Add attending reactions
    for emoji_key, users, label in attending_reactions:
        count = len(users)
        
        try:
            emoji_obj = discord.PartialEmoji.from_str(emoji_key)
            if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                clean_name = EMOJI_MAP[emoji_obj.id][0]
            else:
                clean_name = emoji_obj.name.replace('_', ' ').title() if hasattr(emoji_obj, 'name') else "Unknown"
            
            field_name = f"{clean_name} ({count})"
            
            if hasattr(emoji_obj, 'id') and emoji_obj.id:
                emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
            else:
                emoji_display = str(emoji_obj)
                
        except:
            field_name = f"{label} ({count})"
            emoji_display = emoji_key
        
        if users:
            user_list = f"{emoji_display}\n" + "\n".join([user for user in sorted(users)])
        else:
            user_list = f"{emoji_display}\nNone"
        
        if len(user_list) > 1024:
            user_list = user_list[:1020] + "..."
        
        embed.add_field(name=field_name, value=user_list, inline=True)
    
    # Add other reactions
    for emoji_key, users, label in other_reactions:
        if "Not attending" in label:
            count = len(users)
            try:
                emoji_obj = discord.PartialEmoji.from_str(emoji_key)
                if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                    clean_name = EMOJI_MAP[emoji_obj.id][0]
                else:
                    clean_name = "Not attending"
                
                field_name = f"{clean_name} ({count})"
                
                if hasattr(emoji_obj, 'id') and emoji_obj.id:
                    emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
                else:
                    emoji_display = "🚫"
            except:
                field_name = f"Not attending ({count})"
                emoji_display = "🚫"
            
            user_list = f"{emoji_display}\n{count} not attending"
            
        else:
            count = len(users)
            try:
                emoji_obj = discord.PartialEmoji.from_str(emoji_key)
                if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                    clean_name = EMOJI_MAP[emoji_obj.id][0]
                elif "Late" in label:
                    clean_name = "Late"
                else:
                    clean_name = emoji_obj.name.replace('_', ' ').title() if hasattr(emoji_obj, 'name') else "Unknown"
                
                field_name = f"{clean_name} ({count})"
                
                if hasattr(emoji_obj, 'id') and emoji_obj.id:
                    emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
                else:
                    emoji_display = str(emoji_obj)
            except:
                field_name = f"{label} ({count})"
                emoji_display = emoji_key
            
            if users:
                user_list = f"{emoji_display}\n" + "\n".join([user for user in sorted(users)])
            else:
                user_list = f"{emoji_display}\nNone"
        
        if len(user_list) > 1024:
            user_list = user_list[:1020] + "..."
        
        embed.add_field(name=field_name, value=user_list, inline=True)
    
    embed.set_footer(text=f"Last updated: {datetime.utcnow().strftime('%H:%M UTC')}")
    return embed

async def sync_recent_reactions(limit=10):
    """Sync reactions from recent messages"""
    print(f"Syncing reactions from last {limit} messages...")
    
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        if not monitor_channel:
            print("Monitor channel not found!")
            return
        
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            print("Log channel not found!")
            return
        
        reaction_signups.clear()
        summary_messages.clear()
        summary_threads.clear()
        
        messages = []
        async for message in monitor_channel.history(limit=limit):
            if message.reactions:
                messages.append(message)
        
        print(f"Found {len(messages)} messages with reactions")
        
        for message in messages:
            print(f"Processing message {message.id}...")
            
            for reaction in message.reactions:
                emoji_str = str(reaction.emoji)
                
                async for user in reaction.users():
                    if not user.bot:
                        reaction_signups[message.id][emoji_str].add(user.name)
        
        print("Reaction sync completed!")
        
        for message in messages:
            if message.id in reaction_signups:
                title, timestamp_str = extract_title_and_timestamp(message.content)
                await post_or_edit_summary(log_channel, message.id, title, timestamp_str)
        
    except Exception as e:
        print(f"Error during reaction sync: {e}")

async def post_or_edit_summary(log_channel, message_id, title, timestamp_str):
    """Post or edit summary message"""
    summary_embed = build_summary_embed(message_id, title, timestamp_str)
    
    if message_id in summary_messages:
        try:
            summary_message = summary_messages[message_id]
            await summary_message.edit(embed=summary_embed)
            print(f"Updated summary for message {message_id}")
        except discord.NotFound:
            summary_messages.pop(message_id, None)
            summary_message = await log_channel.send(embed=summary_embed)
            summary_messages[message_id] = summary_message
            print(f"Created new summary for message {message_id}")
    else:
        summary_message = await log_channel.send(embed=summary_embed)
        summary_messages[message_id] = summary_message
        print(f"Created new summary for message {message_id}")

async def get_or_create_thread(summary_message, title):
    """Get or create thread for summary message"""
    try:
        if summary_message.id in summary_threads:
            thread = summary_threads[summary_message.id]
            await thread.fetch()
            return thread, False
    except (discord.NotFound, AttributeError):
        summary_threads.pop(summary_message.id, None)

    thread = await summary_message.create_thread(
        name=f"Reactions for {title}",
        auto_archive_duration=1440
    )
    summary_threads[summary_message.id] = thread
    return thread, True

def log_line(user, emoji, action):
    """Create log line for thread"""
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    if hasattr(emoji, 'id') and emoji.id:
        emoji_display = f"<:{emoji.name}:{emoji.id}>"
    else:
        emoji_display = str(emoji)
    return f"[{time_str}] {user.display_name} {action} reaction {emoji_display}"

@bot.event
async def on_raw_reaction_add(payload):
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

    reaction_signups[payload.message_id][emoji_str].add(user.name)

    title, timestamp_str = extract_title_and_timestamp(message.content)
    await post_or_edit_summary(log_channel, payload.message_id, title, timestamp_str)

    # Create thread for logging
    if payload.message_id in summary_messages:
        summary_message = summary_messages[payload.message_id]
        thread, created = await get_or_create_thread(summary_message, title)
        
        if created:
            try:
                await thread.send(f"🧵 **Reaction log for: {title}**\nAll reaction changes will be logged here.")
            except Exception as e:
                print(f"Failed to send initial thread message: {e}")
        
        try:
            await thread.send(log_line(user, payload.emoji, "added"))
        except Exception as e:
            print(f"Failed to send add log in thread: {e}")

@bot.event
async def on_raw_reaction_remove(payload):
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

    if user.name in reaction_signups[payload.message_id][emoji_str]:
        reaction_signups[payload.message_id][emoji_str].remove(user.name)
        if not reaction_signups[payload.message_id][emoji_str]:
            del reaction_signups[payload.message_id][emoji_str]

    title, timestamp_str = extract_title_and_timestamp(message.content)
    await post_or_edit_summary(log_channel, payload.message_id, title, timestamp_str)

    # Log to thread
    if payload.message_id in summary_messages:
        summary_message = summary_messages[payload.message_id]
        thread, created = await get_or_create_thread(summary_message, title)
        
        if created:
            try:
                await thread.send(f"🧵 **Reaction log for: {title}**\nAll reaction changes will be logged here.")
            except Exception as e:
                print(f"Failed to send initial thread message: {e}")
        
        try:
            await thread.send(log_line(user, payload.emoji, "removed"))
        except Exception as e:
            print(f"Failed to send remove log in thread: {e}")

@bot.command(name="sync_reactions")
async def manual_sync_reactions(ctx, limit: int = 10):
    """Manually sync reactions from recent messages"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    await ctx.send(f"🔄 Syncing reactions from last {limit} messages...")
    await sync_recent_reactions(limit)
    await ctx.send("✅ Reaction sync completed!")

@bot.command(name="test_status")
async def test_status(ctx):
    """Show current bot status"""
    embed = discord.Embed(title="🧪 Bot Test Status", color=0x00FFFF)
    
    total_messages = len(reaction_signups)
    total_reactions = sum(len(emojis) for emojis in reaction_signups.values())
    
    embed.add_field(
        name="📊 Data Status",
        value=f"Tracking {total_messages} messages\nWith {total_reactions} different reactions",
        inline=False
    )
    
    embed.add_field(
        name="📋 Summary Status",
        value=f"Active summaries: {len(summary_messages)}\nActive threads: {len(summary_threads)}",
        inline=False
    )
    
    embed.add_field(
        name="🎯 Channel Config",
        value=f"Monitor: <#{MONITOR_CHANNEL_ID}>\nLogs: <#{LOG_CHANNEL_ID}>",
        inline=False
    )
    
    await ctx.send(embed=embed)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
