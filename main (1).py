import os
import asyncio
import random
import re
from collections import Counter
from datetime import datetime, timedelta

import discord
from discord import ui, Interaction, app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Не найдена переменная окружения DISCORD_TOKEN.")

CHANNEL_ID = 1543007392315474080
ADMIN_IDS = [1416863224430596107]
NOTIFICATION_BEFORE_MINUTES = 30
MIN_CHAT_DELAY_SECONDS = 30 * 60
MAX_CHAT_DELAY_SECONDS = 60 * 60

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

active_raids = {}
scheduled_raids = {}
last_raid_message_id = None
next_schedule_id = 1
word_counts = Counter()
phrase_counts = Counter()

SERVER_CHOICES = [
    app_commands.Choice(name="04 Chandler", value="04 Chandler"),
    app_commands.Choice(name="12 Glendale", value="12 Glendale"),
    app_commands.Choice(name="15 Payson", value="15 Payson"),
    app_commands.Choice(name="16 Gilbert", value="16 Gilbert"),
    app_commands.Choice(name="23 Holiday", value="23 Holiday"),
]
FACTION_CHOICES = [app_commands.Choice(name=x, value=x) for x in ("RM", "LCN", "TRB", "YKZ", "WMC")]
YES_NO_CHOICES = [app_commands.Choice(name="Да", value="yes"), app_commands.Choice(name="Нет", value="no")]
FORMAT_CHOICES = [app_commands.Choice(name=x, value=x) for x in ("2x2", "3x3", "4x4", "5x5")]
TIME_CHOICES = [app_commands.Choice(name=f"{h:02d}:{m:02d}", value=f"{h:02d}:{m:02d}") for h in range(16, 22) for m in (0, 20, 40) if not (h == 21 and m > 40)]

def is_admin(user): return user.id in ADMIN_IDS

def parse_format(value):
    values = {"2x2": 2, "3x3": 3, "4x4": 4, "5x5": 5}
    return values[value.lower().replace(" ", "").replace("х", "x")]

def get_start_datetime(value):
    h, m = map(int, value.split(":"))
    now = datetime.now()
    result = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return result + timedelta(days=1) if result <= now else result

def clean_chat_text(text):
    text = re.sub(r"https?://\S+|www\.\S+", "", text.lower().strip())
    text = re.sub(r"<@!?\d+>|<@&\d+>|<#\d+>", "", text)
    return re.sub(r"\s+", " ", text).strip()

def build_embed(data):
    main = "\n".join(f"{i}. <@{u}>" for i, u in enumerate(data["main"], 1)) or "—"
    reserve = "\n".join(f"{i}. <@{u}>" for i, u in enumerate(data["reserve"], 1)) or "—"
    e = discord.Embed(title=f"🏹 Стрела | {data['server']}", color=discord.Color.green())
    for name, value in [("Формат", data["format"]), ("Время начала", data["time"]), ("Против", data["faction"]), ("Оружие", data["weapon"]), ("Создал", f"<@{data['creator_id']}>")]:
        e.add_field(name=name, value=value, inline=True)
    e.add_field(name=f"Основные слоты ({len(data['main'])}/{data['slots_total']})", value=main, inline=False)
    e.add_field(name=f"Резерв ({len(data['reserve'])}/3)", value=reserve, inline=False)
    e.set_footer(text="Нажми кнопку, чтобы записаться или покинуть слот.")
    return e

class RaidView(ui.View):
    def __init__(self, data):
        super().__init__(timeout=None); self.data = data; self.message = None; self.lock = asyncio.Lock()
    async def update_message(self):
        if self.message: await self.message.edit(embed=build_embed(self.data), view=self)
    @ui.button(label="Взять основной слот", style=discord.ButtonStyle.green, custom_id="main_slot")
    async def main_button(self, interaction: Interaction, button: ui.Button):
        async with self.lock:
            u = interaction.user.id
            if u in self.data["main"]:
                await interaction.response.send_message("Ты уже записан в основные слоты.", ephemeral=True); return
            if len(self.data["main"]) >= self.data["slots_total"]:
                await interaction.response.send_message("Основные слоты заполнены. Можешь записаться в резерв.", ephemeral=True); return
            from_reserve = u in self.data["reserve"]
            if from_reserve: self.data["reserve"].remove(u)
            self.data["main"].append(u); number = len(self.data["main"])
            await interaction.response.defer(ephemeral=True); await self.update_message()
            text = f"✅ Ты успешно {'переведён из резерва в основу' if from_reserve else 'взял основной слот'} №**{number}**.\nПокинуть слот можно кнопкой **«Покинуть слот»**."
            await interaction.followup.send(text, ephemeral=True)
    @ui.button(label="Взять резерв", style=discord.ButtonStyle.secondary, custom_id="reserve_slot")
    async def reserve_button(self, interaction: Interaction, button: ui.Button):
        async with self.lock:
            u = interaction.user.id
            if u in self.data["reserve"]:
                await interaction.response.send_message("Ты уже записан в резерв.", ephemeral=True); return
            if u in self.data["main"]:
                await interaction.response.send_message("Ты уже записан в основные слоты.", ephemeral=True); return
            if len(self.data["reserve"]) >= 3:
                await interaction.response.send_message("Резерв заполнен. Максимум: 3 игрока.", ephemeral=True); return
            self.data["reserve"].append(u); number = len(self.data["reserve"])
            await interaction.response.defer(ephemeral=True); await self.update_message()
            await interaction.followup.send(f"✅ Ты успешно взял резервный слот №**{number}**.\nПокинуть слот можно кнопкой **«Покинуть слот»**.", ephemeral=True)
    @ui.button(label="Покинуть слот", style=discord.ButtonStyle.danger, custom_id="leave_slot")
    async def leave_button(self, interaction: Interaction, button: ui.Button):
        async with self.lock:
            u = interaction.user.id
            if u in self.data["main"]: self.data["main"].remove(u); place = "основные слоты"
            elif u in self.data["reserve"]: self.data["reserve"].remove(u); place = "резерв"
            else:
                await interaction.response.send_message("Ты не записан в эту стрелу.", ephemeral=True); return
            await interaction.response.defer(ephemeral=True); await self.update_message()
            await interaction.followup.send(f"✅ Ты успешно покинул {place}.", ephemeral=True)

async def get_target_channel():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        try: channel = await bot.fetch_channel(CHANNEL_ID)
        except discord.DiscordException: return None
    return channel if isinstance(channel, (discord.TextChannel, discord.Thread)) else None

async def publish_raid(number):
    global last_raid_message_id
    raid = scheduled_raids.get(number)
    if not raid: return
    wait = (raid["publish_time"] - datetime.now()).total_seconds()
    if wait > 0: await asyncio.sleep(wait)
    raid = scheduled_raids.get(number)
    if not raid: return
    channel = await get_target_channel()
    if not channel: scheduled_raids.pop(number, None); return
    data = raid["data"]
    mins = max(0, int((raid["start_time"] - datetime.now()).total_seconds() / 60))
    text = "🏹 Стрела начинается прямо сейчас!" if mins == 0 else f"🏹 Через {mins} минут стрела!"
    try:
        await channel.send(f"@everyone {text}\nСервер: **{data['server']}**\nПротив: **{data['faction']}**\nОружие: **{data['weapon']}**\nФормат: **{data['format']}**\nВремя начала: **{data['time']}**", allowed_mentions=discord.AllowedMentions(everyone=True, users=False, roles=False))
        view = RaidView(data); msg = await channel.send(embed=build_embed(data), view=view); view.message = msg
        active_raids[msg.id] = {"data": data, "view": view}; last_raid_message_id = msg.id
    finally: scheduled_raids.pop(number, None)

async def random_chat_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(random.randint(MIN_CHAT_DELAY_SECONDS, MAX_CHAT_DELAY_SECONDS))
        channel = await get_target_channel()
        if not channel: continue
        if phrase_counts and random.choice([True, True, False]):
            text = random.choice([x for x, _ in phrase_counts.most_common(30)])
        elif word_counts: text = random.choice([x for x, _ in word_counts.most_common(30)])
        else: continue
        await channel.send(f"💬 {text}", allowed_mentions=discord.AllowedMentions.none())

@bot.event
async def on_message(message):
    if message.guild and not message.author.bot and message.channel.id == CHANNEL_ID:
        text = clean_chat_text(message.content)
        if text and not text.startswith(("!", "/")):
            words = re.findall(r"[a-zа-яё0-9]{3,}", text, flags=re.I); word_counts.update(words)
            if 2 <= len(words) <= 10 and len(text) <= 120: phrase_counts[text] += 1
    await bot.process_commands(message)

@bot.tree.command(name="slot", description="Запланировать новую стрелу")
@app_commands.describe(server="Выбери сервер", faction="Фракция противника", deagle="Разрешён ли Deagle?", shotgun="Разрешён ли Shotgun?", rifla="Разрешена ли Rifla?", format="Выбери формат", time_str="Время начала")
@app_commands.choices(server=SERVER_CHOICES, faction=FACTION_CHOICES, deagle=YES_NO_CHOICES, shotgun=YES_NO_CHOICES, rifla=YES_NO_CHOICES, format=FORMAT_CHOICES, time_str=TIME_CHOICES)
async def slot(interaction: Interaction, server: app_commands.Choice[str], faction: app_commands.Choice[str], deagle: app_commands.Choice[str], shotgun: app_commands.Choice[str], rifla: app_commands.Choice[str], format: app_commands.Choice[str], time_str: app_commands.Choice[str]):
    global next_schedule_id
    if interaction.guild is not None:
        await interaction.response.send_message("Используй /slot в личных сообщениях с ботом.", ephemeral=True); return
    if not is_admin(interaction.user):
        await interaction.response.send_message("У тебя нет прав для создания стрел.", ephemeral=True); return
    weapons = [name for name, choice in [("Deagle", deagle), ("Shotgun", shotgun), ("Rifla", rifla)] if choice.value == "yes"]
    if not weapons:
        await interaction.response.send_message("Ошибка: нужно выбрать хотя бы одно оружие.", ephemeral=True); return
    start = get_start_datetime(time_str.value); publish = max(start - timedelta(minutes=NOTIFICATION_BEFORE_MINUTES), datetime.now())
    n = next_schedule_id; next_schedule_id += 1
    data = {"server": server.value, "faction": faction.value, "weapon": ", ".join(weapons), "format": format.value, "slots_total": parse_format(format.value), "time": time_str.value, "creator_id": interaction.user.id, "main": [], "reserve": []}
    scheduled_raids[n] = {"data": data, "start_time": start, "publish_time": publish, "task": None}
    scheduled_raids[n]["task"] = asyncio.create_task(publish_raid(n))
    await interaction.response.send_message(f"✅ Стрела #{n} запланирована.\nСервер: **{server.value}**\nПротив: **{faction.value}**\nОружие: **{', '.join(weapons)}**\nФормат: **{format.value}**\nНачало: **{start:%d.%m.%Y %H:%M}**\nУведомление и слоты: **{publish:%d.%m.%Y %H:%M}**", ephemeral=True)

@bot.tree.command(name="strels", description="Показать все запланированные стрелы")
async def strels(interaction: Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Команду /strels нельзя использовать в личных сообщениях.", ephemeral=True); return
    if not scheduled_raids:
        await interaction.response.send_message("📋 Сейчас нет запланированных стрел."); return
    lines = [f"**#{n}** — **{r['data']['server']}** | против **{r['data']['faction']}** | оружие: **{r['data']['weapon']}** | **{r['data']['format']}** | начало: **{r['start_time']:%d.%m %H:%M}** | слоты: **{r['publish_time']:%d.%m %H:%M}**" for n, r in sorted(scheduled_raids.items())]
    await interaction.response.send_message("📋 **Запланированные стрелы:**\n\n" + "\n".join(lines))

@bot.tree.command(name="dstrel", description="Отменить запланированную стрелу")
@app_commands.describe(number="Номер стрелы из /strels")
async def dstrel(interaction: Interaction, number: int):
    if interaction.guild is not None or not is_admin(interaction.user):
        await interaction.response.send_message("Команда доступна только администратору в личных сообщениях.", ephemeral=True); return
    raid = scheduled_raids.get(number)
    if not raid:
        await interaction.response.send_message("Стрела не найдена или уже опубликована.", ephemeral=True); return
    raid["task"].cancel(); scheduled_raids.pop(number, None)
    await interaction.response.send_message(f"❌ Стрела #{number} отменена.", ephemeral=True)

async def current_raid(interaction):
    if interaction.guild is None or not is_admin(interaction.user):
        await interaction.response.send_message("Команда доступна только администратору на сервере.", ephemeral=True); return None
    raid = active_raids.get(last_raid_message_id)
    if not raid: await interaction.response.send_message("Сейчас нет активной стрелы.", ephemeral=True)
    return raid

@bot.tree.command(name="dslot", description="Удалить игрока из активной стрелы")
@app_commands.describe(user="Игрок")
async def dslot(interaction: Interaction, user: discord.Member):
    raid = await current_raid(interaction)
    if not raid: return
    data, view = raid["data"], raid["view"]
    async with view.lock:
        if user.id in data["main"]: data["main"].remove(user.id)
        elif user.id in data["reserve"]: data["reserve"].remove(user.id)
        else: await interaction.response.send_message("Этот игрок не записан в слоты.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True); await view.update_message()
    await interaction.followup.send(f"{user.mention} удалён из слотов.", ephemeral=True)

@bot.tree.command(name="addslot", description="Добавить игрока в основные слоты")
@app_commands.describe(user="Игрок")
async def addslot(interaction: Interaction, user: discord.Member):
    raid = await current_raid(interaction)
    if not raid: return
    data, view = raid["data"], raid["view"]
    async with view.lock:
        if user.id in data["main"]: await interaction.response.send_message("Этот игрок уже в основных слотах.", ephemeral=True); return
        if len(data["main"]) >= data["slots_total"]: await interaction.response.send_message("Основные слоты заполнены.", ephemeral=True); return
        if user.id in data["reserve"]: data["reserve"].remove(user.id)
        data["main"].append(user.id)
        await interaction.response.defer(ephemeral=True); await view.update_message()
    await interaction.followup.send(f"{user.mention} добавлен в основные слоты.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Бот готов: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="Пикни слот на стрелу, чудище!"))
    synced = await bot.tree.sync(); print(f"Синхронизировано slash-команд: {len(synced)}")
    if not hasattr(bot, "random_chat_task"): bot.random_chat_task = asyncio.create_task(random_chat_loop())

if __name__ == "__main__": bot.run(TOKEN)
