import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import re
import time
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import os

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Database initialization
async def init_db():
    async with aiosqlite.connect('moderation.db') as db:
        # Warnings table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                guild_id INTEGER,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # User levels table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_levels (
                user_id INTEGER,
                guild_id INTEGER,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                last_message DATETIME,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        
        # Guild configuration table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                automod_enabled BOOLEAN DEFAULT FALSE,
                automod_log_channel INTEGER,
                leveling_channel INTEGER,
                spam_channels TEXT DEFAULT '',
                link_channels TEXT DEFAULT '',
                welcomer_enabled BOOLEAN DEFAULT FALSE,
                welcomer_channel INTEGER,
                staff_roles TEXT DEFAULT '',
                ticket_category INTEGER
            )
        ''')
        
        # Level roles table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS level_roles (
                guild_id INTEGER,
                level INTEGER,
                role_id INTEGER,
                PRIMARY KEY (guild_id, level, role_id)
            )
        ''')
        
        # User automod warnings table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS automod_warnings (
                user_id INTEGER,
                guild_id INTEGER,
                warning_count INTEGER DEFAULT 0,
                last_warning DATETIME,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        
        # User accounts table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_accounts (
                user_id INTEGER,
                guild_id INTEGER,
                ign TEXT,
                linked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        
        # Tickets table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                guild_id INTEGER,
                channel_id INTEGER,
                ticket_type TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                closed BOOLEAN DEFAULT FALSE
            )
        ''')
        
        await db.commit()

# Helper functions
def parse_time(time_str):
    """Parse time string like '1h', '30m', '2d' into timedelta"""
    if not time_str:
        return None
    
    match = re.match(r'(\d+)([mhdmo]+)', time_str.lower())
    if not match:
        return None
    
    amount, unit = match.groups()
    amount = int(amount)
    
    if unit == 'm':
        return timedelta(minutes=amount)
    elif unit == 'h':
        return timedelta(hours=amount)
    elif unit == 'd':
        return timedelta(days=amount)
    elif unit == 'mo':
        return relativedelta(months=amount)
    
    return None

async def is_staff(ctx):
    """Check if user is staff (has manage messages permission or has staff role)"""
    if ctx.author.guild_permissions.manage_messages:
        return True
    
    # Check if user has any staff roles
    async with aiosqlite.connect('moderation.db') as db:
        cursor = await db.execute(
            'SELECT staff_roles FROM guild_config WHERE guild_id = ?',
            (ctx.guild.id,)
        )
        result = await cursor.fetchone()
        
        if result and result[0]:
            staff_role_ids = result[0].split(',')
            user_role_ids = [str(role.id) for role in ctx.author.roles]
            return any(role_id in staff_role_ids for role_id in user_role_ids)
    
    return False

# Bad words list (basic example - you can expand this)
BAD_WORDS = ['badword1', 'badword2', 'spam', 'test_bad']  # Add your bad words here

# Automod functions
async def check_spam(message):
    """Check if message is spam (3 consecutive messages)"""
    if not message.guild:
        return False
    
    channel = message.channel
    async for msg in channel.history(limit=3):
        if msg.author != message.author:
            return False
    return True

async def check_emoji_spam(content):
    """Check if message has more than 5 consecutive emojis"""
    emoji_pattern = r'<:[^:]+:\d+>|[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]'
    emojis = re.findall(emoji_pattern, content)
    return len(emojis) > 5

async def check_bad_words(content):
    """Check if message contains bad words"""
    content_lower = content.lower()
    return any(bad_word in content_lower for bad_word in BAD_WORDS)

async def check_links(content):
    """Check if message contains links"""
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return bool(re.search(url_pattern, content))

# Bot events
@bot.event
async def on_ready():
    print(f'{bot.user} has logged in!')
    await init_db()
    if not level_check.is_running():
        level_check.start()

@bot.event
async def on_member_join(member):
    """Handle new member joins for welcomer system"""
    guild_id = member.guild.id
    
    async with aiosqlite.connect('moderation.db') as db:
        cursor = await db.execute(
            'SELECT welcomer_enabled, welcomer_channel FROM guild_config WHERE guild_id = ?',
            (guild_id,)
        )
        result = await cursor.fetchone()
        
        if result and result[0] and result[1]:  # welcomer enabled and channel set
            channel = bot.get_channel(result[1])
            if channel:
                welcome_message = f"Welcome! <@{member.id}> Thanks for joining my server you are **GOAT** <:w_trkis:1400194042234667120> <:GOAT:1400194575125188811>"
                await channel.send(welcome_message)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Process leveling
    await process_leveling(message)
    
    # Process automod
    await process_automod(message)
    
    await bot.process_commands(message)

async def process_leveling(message):
    """Process user leveling system"""
    if not message.guild:
        return
    
    user_id = message.author.id
    guild_id = message.guild.id
    
    async with aiosqlite.connect('moderation.db') as db:
        # Check if user exists in leveling system
        cursor = await db.execute(
            'SELECT xp, level, last_message FROM user_levels WHERE user_id = ? AND guild_id = ?',
            (user_id, guild_id)
        )
        result = await cursor.fetchone()
        
        now = datetime.now()
        
        if result:
            xp, level, last_message_str = result
            last_message = datetime.fromisoformat(last_message_str) if last_message_str else now
            
            # Only give XP if 60 seconds have passed since last message
            if (now - last_message).total_seconds() >= 60:
                xp += 15  # Give 15 XP per message
                new_level = xp // 100  # Level up every 100 XP
                
                await db.execute(
                    'UPDATE user_levels SET xp = ?, level = ?, last_message = ? WHERE user_id = ? AND guild_id = ?',
                    (xp, new_level, now.isoformat(), user_id, guild_id)
                )
                
                # Check if leveled up
                if new_level > level:
                    await handle_level_up(message, new_level)
        else:
            # Create new user entry
            await db.execute(
                'INSERT INTO user_levels (user_id, guild_id, xp, level, last_message) VALUES (?, ?, ?, ?, ?)',
                (user_id, guild_id, 15, 0, now.isoformat())
            )
        
        await db.commit()

async def handle_level_up(message, new_level):
    """Handle level up notification and role assignment"""
    guild_id = message.guild.id
    user_id = message.author.id
    
    async with aiosqlite.connect('moderation.db') as db:
        # Get leveling channel
        cursor = await db.execute(
            'SELECT leveling_channel FROM guild_config WHERE guild_id = ?',
            (guild_id,)
        )
        result = await cursor.fetchone()
        
        if result and result[0]:
            channel = bot.get_channel(result[0])
            if channel:
                await channel.send(
                    f"**Thanks For Showing Your Activity <@{user_id}>! You just Stumbled Up To Level **{new_level}**. Keep GOING!!!!!** <:abilities:1402690411759407185>"
                )
        
        # Check for level roles
        cursor = await db.execute(
            'SELECT role_id FROM level_roles WHERE guild_id = ? AND level = ?',
            (guild_id, new_level)
        )
        roles = await cursor.fetchall()
        
        for role_tuple in roles:
            role_id = role_tuple[0]
            role = message.guild.get_role(role_id)
            if role:
                try:
                    await message.author.add_roles(role)
                except:
                    pass  # Ignore errors if can't assign role

async def process_automod(message):
    """Process automod checks"""
    if not message.guild or message.author.guild_permissions.manage_messages:
        return
    
    guild_id = message.guild.id
    
    async with aiosqlite.connect('moderation.db') as db:
        # Check if automod is enabled
        cursor = await db.execute(
            'SELECT automod_enabled, automod_log_channel, spam_channels, link_channels FROM guild_config WHERE guild_id = ?',
            (guild_id,)
        )
        result = await cursor.fetchone()
        
        if not result or not result[0]:  # Automod not enabled
            return
        
        automod_enabled, log_channel_id, spam_channels, link_channels = result
        spam_channel_ids = spam_channels.split(',') if spam_channels else []
        link_channel_ids = link_channels.split(',') if link_channels else []
        
        violations = []
        
        # Check spam (if not in spam channel)
        if str(message.channel.id) not in spam_channel_ids:
            if await check_spam(message):
                violations.append("spam")
        
        # Check emoji spam
        if await check_emoji_spam(message.content):
            violations.append("emoji spam")
        
        # Check bad words
        if await check_bad_words(message.content):
            violations.append("inappropriate language")
        
        # Check links (if not in link channel)
        if str(message.channel.id) not in link_channel_ids:
            if await check_links(message.content):
                violations.append("unauthorized links")
        
        if violations:
            await handle_automod_violation(message, violations, log_channel_id)

async def handle_automod_violation(message, violations, log_channel_id):
    """Handle automod violations"""
    user_id = message.author.id
    guild_id = message.guild.id
    
    async with aiosqlite.connect('moderation.db') as db:
        # Get user's current warning count
        cursor = await db.execute(
            'SELECT warning_count FROM automod_warnings WHERE user_id = ? AND guild_id = ?',
            (user_id, guild_id)
        )
        result = await cursor.fetchone()
        
        warning_count = result[0] + 1 if result else 1
        
        # Update warning count
        await db.execute(
            'INSERT OR REPLACE INTO automod_warnings (user_id, guild_id, warning_count, last_warning) VALUES (?, ?, ?, ?)',
            (user_id, guild_id, warning_count, datetime.now().isoformat())
        )
        await db.commit()
        
        # Delete the violating message
        try:
            await message.delete()
        except:
            pass
        
        # Send DM warning
        try:
            violation_text = ", ".join(violations)
            await message.author.send(
                f"Warning! Your message in **{message.guild.name}** was removed for: {violation_text}. "
                f"This is warning {warning_count}/3. At 3 warnings, you will be temporarily muted."
            )
        except:
            pass  # Ignore if can't DM user
        
        # Log the violation
        if log_channel_id:
            log_channel = bot.get_channel(log_channel_id)
            if log_channel:
                embed = discord.Embed(
                    title="Automod Violation",
                    color=0xff0000,
                    timestamp=datetime.now()
                )
                embed.add_field(name="User", value=f"{message.author.mention}", inline=True)
                embed.add_field(name="Channel", value=f"{message.channel.mention}", inline=True)
                embed.add_field(name="Violations", value=", ".join(violations), inline=True)
                embed.add_field(name="Warning Count", value=f"{warning_count}/3", inline=True)
                await log_channel.send(embed=embed)
        
        # Auto-mute at 3 warnings
        if warning_count >= 3:
            try:
                timeout_until = datetime.now() + timedelta(minutes=10)
                await message.author.timeout(timeout_until, reason="Automod: 3 violations reached")
                
                # Reset warning count
                await db.execute(
                    'UPDATE automod_warnings SET warning_count = 0 WHERE user_id = ? AND guild_id = ?',
                    (user_id, guild_id)
                )
                await db.commit()
                
                try:
                    await message.author.send(
                        f"You have been automatically muted for 10 minutes in **{message.guild.name}** "
                        "for reaching 3 automod violations."
                    )
                except:
                    pass
            except:
                pass  # Ignore if can't timeout user

# Moderation Commands
@bot.command()
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    """Warn a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    async with aiosqlite.connect('moderation.db') as db:
        await db.execute(
            'INSERT INTO warnings (user_id, guild_id, reason) VALUES (?, ?, ?)',
            (member.id, ctx.guild.id, reason)
        )
        await db.commit()
    
    embed = discord.Embed(
        title="User Warned",
        color=0xffaa00,
        timestamp=datetime.now()
    )
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=True)
    embed.add_field(name="Warned by", value=ctx.author.mention, inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def warn_hs(ctx, member: discord.Member):
    """View user's warning history"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    async with aiosqlite.connect('moderation.db') as db:
        cursor = await db.execute(
            'SELECT reason, timestamp FROM warnings WHERE user_id = ? AND guild_id = ? ORDER BY timestamp DESC',
            (member.id, ctx.guild.id)
        )
        warnings = await cursor.fetchall()
    
    if not warnings:
        await ctx.send(f"{member.mention} has no warnings.")
        return
    
    embed = discord.Embed(
        title=f"Warning History for {member.display_name}",
        color=0x0099ff,
        timestamp=datetime.now()
    )
    
    for i, (reason, timestamp) in enumerate(warnings[:10], 1):  # Show last 10 warnings
        embed.add_field(
            name=f"Warning {i}",
            value=f"**Reason:** {reason}\n**Date:** {timestamp}",
            inline=False
        )
    
    embed.set_footer(text=f"Total warnings: {len(warnings)}")
    await ctx.send(embed=embed)

@bot.command()
async def warn_rmv(ctx, member: discord.Member, number: int):
    """Remove a specific number of warnings from a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    async with aiosqlite.connect('moderation.db') as db:
        # Get warning IDs to remove
        cursor = await db.execute(
            'SELECT id FROM warnings WHERE user_id = ? AND guild_id = ? ORDER BY timestamp DESC LIMIT ?',
            (member.id, ctx.guild.id, number)
        )
        warning_ids = await cursor.fetchall()
        
        if not warning_ids:
            await ctx.send(f"{member.mention} has no warnings to remove.")
            return
        
        # Remove the warnings
        ids_to_remove = [str(w[0]) for w in warning_ids]
        await db.execute(
            f'DELETE FROM warnings WHERE id IN ({",".join(ids_to_remove)})'
        )
        await db.commit()
    
    removed_count = len(warning_ids)
    await ctx.send(f"Removed {removed_count} warning(s) from {member.mention}.")

@bot.command()
async def mute(ctx, member: discord.Member, time_str: str = None, *, reason="No reason provided"):
    """Mute a user for a specified time (1m to 7d)"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    if not time_str:
        await ctx.send("Please provide a time duration (e.g., 30m, 2h, 1d).")
        return
    
    duration = parse_time(time_str)
    if not duration:
        await ctx.send("Invalid time format. Use m (minutes), h (hours), d (days).")
        return
    
    # Check if duration is within limits (1m to 7d)
    min_duration = timedelta(minutes=1)
    max_duration = timedelta(days=7)
    
    # Convert relativedelta to timedelta for comparison if needed
    if hasattr(duration, 'months') and duration.months > 0:
        # If it's a month duration, convert to approximate days
        duration_for_check = timedelta(days=duration.months * 30)
    else:
        duration_for_check = duration
    
    if duration_for_check < min_duration or duration_for_check > max_duration:
        await ctx.send("Mute duration must be between 1 minute and 7 days.")
        return
    
    try:
        timeout_until = datetime.now() + duration
        await member.timeout(timeout_until, reason=f"Muted by {ctx.author.name}: {reason}")
        
        embed = discord.Embed(
            title="User Muted",
            color=0xff0000,
            timestamp=datetime.now()
        )
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Duration", value=time_str, inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        embed.add_field(name="Muted by", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to timeout this user.")
    except Exception as e:
        await ctx.send(f"Error muting user: {str(e)}")

@bot.command()
async def unmute(ctx, member: discord.Member):
    """Unmute a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    try:
        await member.timeout(None, reason=f"Unmuted by {ctx.author.name}")
        await ctx.send(f"{member.mention} has been unmuted.")
    except discord.Forbidden:
        await ctx.send("I don't have permission to remove timeout from this user.")
    except Exception as e:
        await ctx.send(f"Error unmuting user: {str(e)}")

@bot.command()
async def ban(ctx, member: discord.Member, time_str: str = None, *, reason="No reason provided"):
    """Ban a user (temporarily if time is specified)"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    try:
        await member.ban(reason=f"Banned by {ctx.author.name}: {reason}")
        
        embed = discord.Embed(
            title="User Banned",
            color=0x000000,
            timestamp=datetime.now()
        )
        embed.add_field(name="User", value=str(member), inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        embed.add_field(name="Banned by", value=ctx.author.mention, inline=True)
        
        if time_str:
            duration = parse_time(time_str)
            if duration:
                embed.add_field(name="Duration", value=time_str, inline=True)
                # Schedule unban (simplified - in production you'd want a proper task scheduler)
                asyncio.create_task(schedule_unban(ctx.guild, member, duration))
        
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to ban this user.")
    except Exception as e:
        await ctx.send(f"Error banning user: {str(e)}")

async def schedule_unban(guild, member, duration):
    """Schedule automatic unban"""
    await asyncio.sleep(duration.total_seconds())
    try:
        await guild.unban(member, reason="Temporary ban expired")
    except:
        pass  # Ignore errors

@bot.command()
async def unban(ctx, *, member_name):
    """Unban a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    banned_users = [entry async for entry in ctx.guild.bans()]
    
    for ban_entry in banned_users:
        user = ban_entry.user
        if user.name.lower() == member_name.lower() or str(user) == member_name:
            try:
                await ctx.guild.unban(user, reason=f"Unbanned by {ctx.author.name}")
                await ctx.send(f"{user} has been unbanned.")
                return
            except Exception as e:
                await ctx.send(f"Error unbanning user: {str(e)}")
                return
    
    await ctx.send(f"User '{member_name}' not found in ban list.")

@bot.command()
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    """Kick a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    try:
        await member.kick(reason=f"Kicked by {ctx.author.name}: {reason}")
        
        embed = discord.Embed(
            title="User Kicked",
            color=0xffa500,
            timestamp=datetime.now()
        )
        embed.add_field(name="User", value=str(member), inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        embed.add_field(name="Kicked by", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to kick this user.")
    except Exception as e:
        await ctx.send(f"Error kicking user: {str(e)}")

# Configuration Commands
@bot.command()
async def welcomer_enable(ctx, channel: discord.TextChannel):
    """Enable welcomer system for the server"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    async with aiosqlite.connect('moderation.db') as db:
        await db.execute(
            'INSERT OR REPLACE INTO guild_config (guild_id, welcomer_enabled, welcomer_channel) VALUES (?, ?, ?) '
            'ON CONFLICT(guild_id) DO UPDATE SET welcomer_enabled = ?, welcomer_channel = ?',
            (ctx.guild.id, True, channel.id, True, channel.id)
        )
        await db.commit()
    
    await ctx.send(f"Welcomer system has been enabled! Welcome messages will be sent to {channel.mention}.")

@bot.command()
async def automod_enable(ctx):
    """Enable automod for the server"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    async with aiosqlite.connect('moderation.db') as db:
        await db.execute(
            'INSERT OR REPLACE INTO guild_config (guild_id, automod_enabled) VALUES (?, ?)',
            (ctx.guild.id, True)
        )
        await db.commit()
    
    await ctx.send("Automod has been enabled for this server.")

@bot.command()
async def automod_log(ctx, channel: discord.TextChannel):
    """Set the automod log channel"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    async with aiosqlite.connect('moderation.db') as db:
        await db.execute(
            'INSERT OR REPLACE INTO guild_config (guild_id, automod_log_channel) VALUES (?, ?) '
            'ON CONFLICT(guild_id) DO UPDATE SET automod_log_channel = ?',
            (ctx.guild.id, channel.id, channel.id)
        )
        await db.commit()
    
    await ctx.send(f"Automod log channel set to {channel.mention}.")

@bot.command()
async def spam(ctx, *channels: discord.TextChannel):
    """Set channels where spam is allowed"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    channel_ids = ','.join(str(ch.id) for ch in channels)
    
    async with aiosqlite.connect('moderation.db') as db:
        await db.execute(
            'INSERT OR REPLACE INTO guild_config (guild_id, spam_channels) VALUES (?, ?) '
            'ON CONFLICT(guild_id) DO UPDATE SET spam_channels = ?',
            (ctx.guild.id, channel_ids, channel_ids)
        )
        await db.commit()
    
    channel_mentions = ', '.join(ch.mention for ch in channels)
    await ctx.send(f"Spam is now allowed in: {channel_mentions}")

@bot.command()
async def link(ctx, *channels: discord.TextChannel):
    """Set channels where links are allowed"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    channel_ids = ','.join(str(ch.id) for ch in channels)
    
    async with aiosqlite.connect('moderation.db') as db:
        await db.execute(
            'INSERT OR REPLACE INTO guild_config (guild_id, link_channels) VALUES (?, ?) '
            'ON CONFLICT(guild_id) DO UPDATE SET link_channels = ?',
            (ctx.guild.id, channel_ids, channel_ids)
        )
        await db.commit()
    
    channel_mentions = ', '.join(ch.mention for ch in channels)
    await ctx.send(f"Links are now allowed in: {channel_mentions}")

# Leveling Commands
@bot.command()
async def leveling_channel(ctx, channel: discord.TextChannel):
    """Set the leveling announcement channel"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    async with aiosqlite.connect('moderation.db') as db:
        await db.execute(
            'INSERT OR REPLACE INTO guild_config (guild_id, leveling_channel) VALUES (?, ?) '
            'ON CONFLICT(guild_id) DO UPDATE SET leveling_channel = ?',
            (ctx.guild.id, channel.id, channel.id)
        )
        await db.commit()
    
    await ctx.send(f"Leveling announcements will be sent to {channel.mention}.")

@bot.command()
async def levelrole(ctx, action_or_role, role_or_level=None, level=None):
    """Add or remove level roles"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    if action_or_role.lower() == 'elim':
        # Remove role: !levelrole elim @role
        if not role_or_level:
            await ctx.send("Please specify a role to remove.")
            return
        
        try:
            role = await commands.RoleConverter().convert(ctx, role_or_level)
        except:
            await ctx.send("Invalid role specified.")
            return
        
        async with aiosqlite.connect('moderation.db') as db:
            await db.execute(
                'DELETE FROM level_roles WHERE guild_id = ? AND role_id = ?',
                (ctx.guild.id, role.id)
            )
            await db.commit()
        
        await ctx.send(f"Removed {role.mention} from level rewards.")
    
    else:
        # Add role: !levelrole @role 10
        try:
            role = await commands.RoleConverter().convert(ctx, action_or_role)
            target_level = int(role_or_level) if role_or_level else 0
        except:
            await ctx.send("Usage: `!levelrole @role <level>` or `!levelrole elim @role`")
            return
        
        async with aiosqlite.connect('moderation.db') as db:
            await db.execute(
                'INSERT OR REPLACE INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)',
                (ctx.guild.id, target_level, role.id)
            )
            await db.commit()
        
        await ctx.send(f"Added {role.mention} as reward for reaching level {target_level}.")

@bot.command()
async def level(ctx, member: discord.Member = None):
    """Check a user's level"""
    if member is None:
        member = ctx.author
    
    async with aiosqlite.connect('moderation.db') as db:
        cursor = await db.execute(
            'SELECT xp, level FROM user_levels WHERE user_id = ? AND guild_id = ?',
            (member.id, ctx.guild.id)
        )
        result = await cursor.fetchone()
    
    if not result:
        await ctx.send(f"{member.mention} is not in the leveling system yet.")
        return
    
    xp, level = result
    xp_for_next = (level + 1) * 100
    xp_needed = xp_for_next - xp
    
    embed = discord.Embed(
        title=f"Level Info for {member.display_name}",
        color=0x00ff00
    )
    embed.add_field(name="Current Level", value=level, inline=True)
    embed.add_field(name="Total XP", value=xp, inline=True)
    embed.add_field(name="XP to Next Level", value=xp_needed, inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    await ctx.send(embed=embed)

@bot.command()
async def lock(ctx, *roles: discord.Role):
    """Lock a channel, optionally allowing specific roles"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    channel = ctx.channel
    
    try:
        # Get the @everyone role
        everyone_role = ctx.guild.default_role
        
        # Deny send_messages for @everyone
        await channel.set_permissions(everyone_role, send_messages=False)
        
        # If specific roles are mentioned, allow them to send messages
        if roles:
            for role in roles:
                await channel.set_permissions(role, send_messages=True)
            
            role_mentions = ', '.join(role.mention for role in roles)
            await ctx.send(f"🔒 Channel locked! Only {role_mentions} can send messages.")
        else:
            await ctx.send("🔒 Channel locked for everyone!")
            
    except discord.Forbidden:
        await ctx.send("I don't have permission to modify channel permissions.")
    except Exception as e:
        await ctx.send(f"Error locking channel: {str(e)}")

@bot.command()
async def unlock(ctx):
    """Unlock a channel"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    channel = ctx.channel
    
    try:
        # Reset @everyone permissions to default (None = inherit from category/server)
        everyone_role = ctx.guild.default_role
        await channel.set_permissions(everyone_role, send_messages=None)
        
        # Remove any role-specific overrides that might have been set by lock command
        for overwrite in channel.overwrites:
            if isinstance(overwrite, discord.Role) and overwrite != everyone_role:
                await channel.set_permissions(overwrite, send_messages=None)
        
        await ctx.send("🔓 Channel unlocked!")
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to modify channel permissions.")
    except Exception as e:
        await ctx.send(f"Error unlocking channel: {str(e)}")

# Account linking system
class IGNModal(discord.ui.Modal, title='Link Your Account'):
    def __init__(self):
        super().__init__()
    
    ign = discord.ui.TextInput(
        label='What is your In-game-name?',
        placeholder='Enter your Stumble Guys username...',
        required=True,
        max_length=50
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        async with aiosqlite.connect('moderation.db') as db:
            await db.execute(
                'INSERT OR REPLACE INTO user_accounts (user_id, guild_id, ign) VALUES (?, ?, ?)',
                (interaction.user.id, interaction.guild.id, self.ign.value)
            )
            await db.commit()
        
        embed = discord.Embed(
            title="Account Linked!",
            description=f"Your in-game name has been set to: **{self.ign.value}**",
            color=0x00ff00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class AccountLinkView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='🔗 Link Account', style=discord.ButtonStyle.primary)
    async def link_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IGNModal())

# Ticket system
class TicketView(discord.ui.View):
    def __init__(self, ticket_types):
        super().__init__(timeout=None)
        self.ticket_types = ticket_types
        
        # Add buttons for each ticket type (Discord allows up to 25 buttons per view)
        for i, ticket_type in enumerate(ticket_types):
            # Parse emoji and label from ticket_type
            parts = ticket_type.strip().split(' ', 1)
            # Check if first part is an emoji (custom emoji <:name:id> or unicode emoji)
            if len(parts) == 2 and (parts[0].startswith('<:') or len(parts[0]) <= 2):
                # Has emoji
                emoji = parts[0]
                label = parts[1]
            else:
                # No emoji specified, use default
                emoji = '🎫'
                label = ticket_type.strip()
            
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                emoji=emoji,
                row=i // 5  # Discord allows 5 buttons per row, multiple rows supported
            )
            button.callback = self.create_ticket_callback(label)
            self.add_item(button)
    
    def create_ticket_callback(self, ticket_type):
        async def callback(interaction: discord.Interaction):
            await self.create_ticket(interaction, ticket_type)
        return callback
    
    async def create_ticket(self, interaction: discord.Interaction, ticket_type):
        guild = interaction.guild
        user = interaction.user
        
        # Check if user already has an open ticket
        async with aiosqlite.connect('moderation.db') as db:
            cursor = await db.execute(
                'SELECT channel_id FROM tickets WHERE user_id = ? AND guild_id = ? AND closed = FALSE',
                (user.id, guild.id)
            )
            existing_ticket = await cursor.fetchone()
            
            if existing_ticket:
                channel = guild.get_channel(existing_ticket[0])
                if channel:
                    await interaction.response.send_message(
                        f"You already have an open ticket: {channel.mention}",
                        ephemeral=True
                    )
                    return
        
        # Get ticket category
        async with aiosqlite.connect('moderation.db') as db:
            cursor = await db.execute(
                'SELECT ticket_category FROM guild_config WHERE guild_id = ?',
                (guild.id,)
            )
            result = await cursor.fetchone()
            category = guild.get_channel(result[0]) if result and result[0] else None
        
        # Create ticket channel
        channel_name = f"{ticket_type.lower()}-{user.name}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # Add staff roles to overwrites
        async with aiosqlite.connect('moderation.db') as db:
            cursor = await db.execute(
                'SELECT staff_roles FROM guild_config WHERE guild_id = ?',
                (guild.id,)
            )
            result = await cursor.fetchone()
            
            if result and result[0]:
                staff_role_ids = result[0].split(',')
                for role_id in staff_role_ids:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        try:
            ticket_channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=overwrites
            )
            
            # Save ticket to database
            async with aiosqlite.connect('moderation.db') as db:
                await db.execute(
                    'INSERT INTO tickets (user_id, guild_id, channel_id, ticket_type) VALUES (?, ?, ?, ?)',
                    (user.id, guild.id, ticket_channel.id, ticket_type)
                )
                await db.commit()
            
            # Send welcome message in ticket
            embed = discord.Embed(
                title=f"{ticket_type} Ticket",
                description=f"Thank you for opening a ticket, {user.mention}! A staff member will be with you shortly.",
                color=0x0099ff
            )
            await ticket_channel.send(embed=embed)
            
            await interaction.response.send_message(
                f"Ticket created! {ticket_channel.mention}",
                ephemeral=True
            )
            
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to create channels.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Error creating ticket: {str(e)}",
                ephemeral=True
            )

@bot.command()
async def acc(ctx):
    """Display account linking panel"""
    embed = discord.Embed(
        title="Link your Stumble Guys account",
        description="Click the button below to link your account!",
        color=0x0099ff
    )
    
    view = AccountLinkView()
    await ctx.send(embed=embed, view=view)

@bot.command()
async def IGN(ctx, member: discord.Member = None):
    """Show user's in-game name"""
    if member is None:
        member = ctx.author
    
    async with aiosqlite.connect('moderation.db') as db:
        cursor = await db.execute(
            'SELECT ign, linked_at FROM user_accounts WHERE user_id = ? AND guild_id = ?',
            (member.id, ctx.guild.id)
        )
        result = await cursor.fetchone()
    
    if not result:
        await ctx.send(f"{member.mention} hasn't linked their account yet.")
        return
    
    ign, linked_at = result
    embed = discord.Embed(
        title=f"{member.display_name}'s Account",
        color=0x00ff00
    )
    embed.add_field(name="In-Game Name", value=ign, inline=True)
    embed.add_field(name="Linked", value=linked_at, inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    await ctx.send(embed=embed)

@bot.command()
async def ticket(ctx, *, ticket_types):
    """Create a ticket panel with multiple options"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    # Parse ticket types separated by commas
    types = [t.strip() for t in ticket_types.split(',')]
    
    if len(types) > 25:  # Discord has a limit of 25 buttons per view
        await ctx.send("You can only have up to 25 ticket types.")
        return
    
    embed = discord.Embed(
        title="Support Tickets",
        description="Click a button below if you need help!",
        color=0x0099ff
    )
    
    view = TicketView(types)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def psu(ctx, *roles: discord.Role):
    """Set staff roles that can use moderation commands and see tickets"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("You need administrator permission to use this command.")
        return
    
    if not roles:
        await ctx.send("Please mention at least one role.")
        return
    
    role_ids = ','.join(str(role.id) for role in roles)
    
    async with aiosqlite.connect('moderation.db') as db:
        await db.execute(
            'INSERT OR REPLACE INTO guild_config (guild_id, staff_roles) VALUES (?, ?) '
            'ON CONFLICT(guild_id) DO UPDATE SET staff_roles = ?',
            (ctx.guild.id, role_ids, role_ids)
        )
        await db.commit()
    
    role_mentions = ', '.join(role.mention for role in roles)
    await ctx.send(f"Staff roles updated! These roles can now use moderation commands: {role_mentions}")

@bot.command()
async def commands(ctx):
    """Show all available commands for staff and owners"""
    if not await is_staff(ctx) and not ctx.author.guild_permissions.administrator:
        await ctx.send("You don't have permission to view the command list.")
        return
    
    embed = discord.Embed(
        title="🔧 Bot Commands",
        description="Complete list of available commands",
        color=0x0099ff
    )
    
    # Moderation Commands
    moderation_cmds = [
        "`!warn @user [reason]` - Issue warning to user",
        "`!warn_hs @user` - View user's warning history", 
        "`!warn_rmv @user <number>` - Remove number of warnings",
        "`!mute @user <time> [reason]` - Mute user (1m-7d)",
        "`!unmute @user` - Remove mute from user",
        "`!ban @user [time] [reason]` - Ban user (temp if time given)",
        "`!unban <username>` - Unban user",
        "`!kick @user [reason]` - Kick user from server"
    ]
    
    # Automod Commands
    automod_cmds = [
        "`!automod_enable` - Enable automatic moderation",
        "`!automod_log #channel` - Set automod log channel"
    ]
    
    # Channel Management
    channel_cmds = [
        "`!spam #channel...` - Set spam-allowed channels",
        "`!link #channel...` - Set link-allowed channels", 
        "`!lock [@role...]` - Lock channel (allow roles if given)",
        "`!unlock` - Unlock channel"
    ]
    
    # Leveling System
    leveling_cmds = [
        "`!leveling_channel #channel` - Set level announcement channel",
        "`!levelrole @role <level>` - Add role reward for level",
        "`!levelrole elim @role` - Remove role from rewards",
        "`!level [@user]` - Check user's level and XP"
    ]
    
    # Account & Tickets
    account_cmds = [
        "`!acc` - Show account linking panel",
        "`!IGN [@user]` - Show user's in-game name",
        "`!ticket types,with,emojis` - Create ticket panel",
        "`!welcomer_enable #channel` - Enable welcomer system"
    ]
    
    # Admin Only
    admin_cmds = [
        "`!psu @role...` - Set staff roles (Admin only)",
        "`!commands` - Show this command list"
    ]
    
    embed.add_field(name="⚖️ Moderation", value="\n".join(moderation_cmds), inline=False)
    embed.add_field(name="🤖 Automod", value="\n".join(automod_cmds), inline=False)
    embed.add_field(name="🔒 Channel Management", value="\n".join(channel_cmds), inline=False)
    embed.add_field(name="📈 Leveling System", value="\n".join(leveling_cmds), inline=False)
    embed.add_field(name="🎫 Accounts & Tickets", value="\n".join(account_cmds), inline=False)
    
    if ctx.author.guild_permissions.administrator:
        embed.add_field(name="👑 Administrator Only", value="\n".join(admin_cmds), inline=False)
    
    embed.set_footer(text="All commands require staff permissions unless noted otherwise")
    
    await ctx.send(embed=embed)

# Background task to check level roles
@tasks.loop(minutes=5)
async def level_check():
    """Periodically check and assign level roles"""
    async with aiosqlite.connect('moderation.db') as db:
        cursor = await db.execute(
            'SELECT ul.user_id, ul.guild_id, ul.level, lr.role_id FROM user_levels ul '
            'JOIN level_roles lr ON ul.guild_id = lr.guild_id AND ul.level >= lr.level'
        )
        assignments = await cursor.fetchall()
        
        for user_id, guild_id, user_level, role_id in assignments:
            guild = bot.get_guild(guild_id)
            if not guild:
                continue
            
            member = guild.get_member(user_id)
            role = guild.get_role(role_id)
            
            if member and role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Level role assignment")
                except:
                    pass  # Ignore errors

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("User not found.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing required argument: {error.param}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument provided.")
    else:
        print(f"Unhandled error: {error}")

# Run the bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("Please set the DISCORD_TOKEN environment variable")
    else:
        bot.run(token)