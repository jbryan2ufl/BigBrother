import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
import sqlite3
import signal
import sys
import pandas as pd
from matplotlib.ticker import MaxNLocator
import random
import requests
from dotenv import load_dotenv
import os

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import matplotlib.pyplot as plt

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

conn = sqlite3.connect('call_logs.db')
cursor = conn.cursor()

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

guild = None
role_dict = {}
member_dict = {}
bot_role = None

def get_color_name(hex_code):
    url = f"https://colornames.org/search/json/?hex={hex_code[1:]}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        return data.get("name")  # Extract the "name" field
    else:
        print(f"Error: Received status code {response.status_code}")
        return None

def generate_random_hex_color() -> str:
	color_int = random.randint(0, 0xFFFFFF)
	return f'#{color_int:06x}'

def is_admin(member):
	return member.guild_permissions.administrator

def populate_roles_and_members():
	global member_dict
	global role_dict
	global guild
	global bot_role
	
	guild = bot.guilds[0]

	bot_role = guild.me.top_role

	role_dict = {role.name: role for role in guild.roles}
	member_dict = {member.name: member for member in guild.members}

async def create_role_for_member(member: discord.Member):
	global role_dict
	if member.name not in role_dict:
		role = await guild.create_role(name=member.name)
		await role.edit(position=bot_role.position-1)
		await member.add_roles(role)
		role_dict[member.name] = role
		return role

async def change_member_role_color(member, new_color):
	if member.name in role_dict:
		color = discord.Color.from_str(new_color)
		await role_dict[member.name].edit(color=color)
	
def get_member_role_color(member):
	if member.name in member_dict:
		return role_dict[member.name].color

def create_user_table(user_id):
	cursor.execute(f'''
		CREATE TABLE IF NOT EXISTS user_{user_id} (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			join_time DATETIME,
			leave_time DATETIME
		)
	''')

def open_call(user_id):
	create_user_table(user_id)
	join_time = datetime.now(timezone.utc).isoformat()
	cursor.execute(f'''
		INSERT INTO user_{user_id} (join_time)
		VALUES (?)
	''', (join_time,))
	conn.commit()

def close_call(user_id):
	create_user_table(user_id)
	leave_time = datetime.now(timezone.utc).isoformat()
	cursor.execute(f'''
		UPDATE user_{user_id}
		SET leave_time = ?
		WHERE id = (
			SELECT id
			FROM user_{user_id}
			WHERE leave_time IS NULL
			ORDER BY id DESC
			LIMIT 1
		)
	''', (leave_time,))
	conn.commit()

def get_user_logs(user_id):
	cursor.execute(f'SELECT * FROM user_{user_id}')
	rows = cursor.fetchall()
	return rows

def get_all_user_logs():
	cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
	tables = cursor.fetchall()

	all_logs = {}

	for table in tables:
		table_name = table[0]
		if table_name != 'sqlite_sequence':
			user_id = table_name.replace('user_', '')
			logs = get_user_logs(user_id)
			all_logs[user_id] = logs

	return all_logs

def clear_database():
	cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
	tables = cursor.fetchall()
	for table in tables:
		table_name = table[0]
		if table_name != 'sqlite_sequence':
			cursor.execute(f"DELETE FROM {table_name};")
			cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{table_name}';")
	conn.commit()

def close_database(signal_received, frame):
	print("Bot shutting down...")
	for guild in bot.guilds:
		for channel in guild.voice_channels:
			for member in channel.members:
				user_id = str(member.id)
				close_call(user_id)
	conn.commit()
	conn.close()
	sys.exit()

def generate_card(username, logs):
	width, height = 1200, 600
	canvas = Image.new('RGB', (width, height), 'white')
	draw = ImageDraw.Draw(canvas)

	time_logs = []
	
	for log in logs:
		if log[1] is None:
			continue
		join_time = datetime.fromisoformat(log[1])
		leave_time = datetime.now(timezone.utc) if log[2] is None else datetime.fromisoformat(log[2])

		call_time = (leave_time - join_time).total_seconds()
		time_logs.append((log[0], join_time, leave_time, call_time))
	
	df = pd.DataFrame(time_logs, columns=['ID', 'Start Time', 'End Time', 'Duration'])

	# Plot 1: Histogram of durations
	plt.figure(figsize=(2, 2))
	n, bins, patches = plt.hist(df['Duration'], bins=5, edgecolor='black', color='skyblue')
	bins_int = [int(x) for x in bins]
	plt.xticks(bins_int)
	plt.title('Histogram of Call Durations')
	plt.xlabel('Duration (seconds)')
	plt.ylabel('Frequency')

	# Save plot as an image
	buf1 = BytesIO()
	plt.savefig(buf1, format='PNG', bbox_inches='tight')
	plt.close()  # Close the current figure to prevent overlap

	# Plot 2: Bar chart showing daily call history (total duration for each day)
	df['Date'] = df['Start Time'].dt.date
	daily_calls = df.groupby('Date')['Duration'].sum()

	plt.figure(figsize=(2, 2))
	daily_calls.plot(kind='bar', color='lightgreen')
	plt.title('Daily Call Duration')
	plt.xlabel('Date')
	plt.ylabel('Duration')
	plt.gca().yaxis.set_major_locator(MaxNLocator(integer=True))
	plt.xticks(rotation=45)

	# Save plot as an image
	buf2 = BytesIO()
	plt.savefig(buf2, format='PNG', bbox_inches='tight')
	plt.close()  # Close the current figure to prevent overlap

	buf1.seek(0)
	buf2.seek(0)
	graph_image1 = Image.open(buf1)
	graph_image2 = Image.open(buf2)
	canvas.paste(graph_image1, (600, 10))
	canvas.paste(graph_image2, (600, 250))

	# Define node positions
	nodes = {
		"A": (100, 150),
		"B": (300, 100),
		"C": (500, 200),
		"D": (400, 400),
	}

	# Define connections (edges)
	edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]

	# Draw edges (connections)
	for edge in edges:
		node1, node2 = edge
		draw.line([nodes[node1], nodes[node2]], fill="black", width=2)

	# Draw nodes
	for node, position in nodes.items():
		x, y = position
		draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill="blue", outline="black")
		draw.text((x + 15, y - 10), node, fill="black", font=ImageFont.load_default())

	# Add username text (using a default font if Arial is not available)
	try:
		font_path = "arial.ttf"  # Ensure this font path exists or replace with a default
		font = ImageFont.truetype(font_path, 40)
	except IOError:
		font = ImageFont.load_default()  # Fallback to default font if Arial is not available
	draw.text((10, 10), username, fill="black", font=font)

	# Save the image to a BytesIO buffer
	image_buf = BytesIO()
	canvas.save(image_buf, format="PNG")
	image_buf.seek(0)

	return image_buf

@bot.event
async def on_ready():
	print(f"Bot is online as {bot.user}")

	populate_roles_and_members()

	for guild in bot.guilds:
		for channel in guild.voice_channels:
			for member in channel.members:
				user_id = str(member.id)
				open_call(user_id)

@bot.event
async def on_voice_state_update(member, before, after):
	user_id = str(member.id)

	if before.channel is None and after.channel is not None:
		open_call(user_id)

	if before.channel is not None and after.channel is None:
		close_call(user_id)

@bot.command(help="Creates a member call time info card.")
async def vc_time(ctx, member: discord.Member = None):
	member = member or ctx.author
	user_id = str(member.id)
	
	logs = get_user_logs(user_id)

	buffer = generate_card(member.name, logs)
	await ctx.send(file=discord.File(fp=buffer, filename="user_card.png"))

@bot.command(help="Clears the full user call time database.")
async def clear(ctx):
	if is_admin(ctx.author):
		clear_database()
		await ctx.send("Database cleared.")
	else:
		await ctx.send(f"{ctx.author.name} is not admin.")

@bot.command(help="Creates a user role for color setting.")
async def create_role(ctx, member: discord.Member = None):
	target_member = None
	if member and is_admin(ctx.author):
		target_member = member
	else:
		target_member = ctx.author

	role = await create_role_for_member(target_member)
	await role.edit(position=bot_role.position-1)
	await ctx.send(f"Role created for and assigned to {target_member}.")

@bot.command(help="Sets a color to a valid hex string such as: #AF18CD.")
async def set_color(ctx, color, member: discord.Member = None):
	target_member = None
	if member and is_admin(ctx.author):
		target_member = member
	else:
		target_member = ctx.author

	await change_member_role_color(target_member, color)

	color_name = get_color_name(color)
	if color_name == None:
		await ctx.send(f"Color changed to {color} successfully. This has not been named yet, you can name it at: https://colornames.org/color/{color[1:]}.")
	else:
		await ctx.send(f"Color changed to {color} successfully. This color was named {color_name} at https://colornames.org/color/{color[1:]}.")

@bot.command(help="Sets the member's role to be a random color.")
async def random_color(ctx):
	target_member = ctx.author

	color = generate_random_hex_color()

	await change_member_role_color(target_member, color)

	color_name = get_color_name(color)

	if color_name is None:
		await ctx.send(f"Color changed to {color} successfully. This has not been named yet, you can name it at: https://colornames.org/color/{color[1:]}.")
	else:
		await ctx.send(f"Color changed to {color} successfully. This color was named {color_name} at https://colornames.org/color/{color[1:]}.")

@bot.command(help="Queries member's role color.")
async def what_color(ctx, member: discord.Member = None):
	target_member = member or ctx.author

	color = str(role_dict[target_member.name].color)

	color_name = get_color_name(color)

	if color_name is None:
		await ctx.send(f"{target_member.name}'s color is {color}. This has not been named yet, you can name it at: https://colornames.org/color/{color[1:]}.")
	else:
		await ctx.send(f"{target_member.name}'s color is {color}. This color was named {color_name} at https://colornames.org/color/{color[1:]}.")

signal.signal(signal.SIGINT, close_database)
signal.signal(signal.SIGTERM, close_database)

bot.run(token)
