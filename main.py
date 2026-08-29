import os
import asyncio
import random
import re
from collections import Counter
from datetime import datetime, timedelta

import discord
from discord import ui, Interaction, app_commands
from discord.ext import commands


# ================= НАСТРОЙКИ =================

# На Bothost добавь переменную окружения:
# DISCORD_TOKEN = твой_новый_токен
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "Не найдена переменная окружения DISCORD_TOKEN."
    )

# ID канала, в который бот отправляет стрелы,
# уведомления и случайные фразы
CHANNEL_ID = 1543007392315474080

# ID администраторов.
# Им доступны: /slot, /dstrel, /dslot, /addslot
ADMIN_IDS = [
    1416863224430596107,
]

# За сколько минут до начала стрелы появятся @everyone и карточка
NOTIFICATION_BEFORE_MINUTES = 30

# Через сколько бот может написать случайную фразу
MIN_CHAT_DELAY_SECONDS = 30 * 60
MAX_CHAT_DELAY_SECONDS = 60 * 60

# ===============================================


intents = discord.Intents.default()

# Нужно для чтения текста сообщений участников
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# Активные опубликованные стрелы
active_raids = {}

# Запланированные стрелы
scheduled_raids = {}

# Последняя опубликованная стрела
last_raid_message_id = None

# Номер следующей стрелы
next_schedule_id = 1

# Счётчики популярных слов и фраз
word_counts = Counter()
phrase_counts = Counter()


# ================= ВЫБОРЫ В /slot =================


SERVER_CHOICES = [
    app_commands.Choice(name="04 Chandler", value="04 Chandler"),
    app_commands.Choice(name="12 Glendale", value="12 Glendale"),
    app_commands.Choice(name="15 Payson", value="15 Payson"),
    app_commands.Choice(name="16 Gilbert", value="16 Gilbert"),
    app_commands.Choice(name="23 Holiday", value="23 Holiday"),
]

FACTION_CHOICES = [
    app_commands.Choice(name="RM", value="RM"),
    app_commands.Choice(name="LCN", value="LCN"),
    app_commands.Choice(name="TRB", value="TRB"),
    app_commands.Choice(name="YKZ", value="YKZ"),
    app_commands.Choice(name="WMC", value="WMC"),
]

SIDE_CHOICES = [
    app_commands.Choice(name="Attack", value="Attack"),
    app_commands.Choice(name="Deff", value="Deff"),
]

WEAPON_CHOICES = [
    app_commands.Choice(name="Deagle", value="Deagle"),
    app_commands.Choice(name="Shotgun", value="Shotgun"),
    app_commands.Choice(name="Rifla", value="Rifla"),
]

FORMAT_CHOICES = [
    app_commands.Choice(name="2x2", value="2x2"),
    app_commands.Choice(name="3x3", value="3x3"),
    app_commands.Choice(name="4x4", value="4x4"),
    app_commands.Choice(name="5x5", value="5x5"),
]

TIME_CHOICES = [
    app_commands.Choice(name="16:00", value="16:00"),
    app_commands.Choice(name="16:20", value="16:20"),
    app_commands.Choice(name="16:40", value="16:40"),
    app_commands.Choice(name="17:00", value="17:00"),
    app_commands.Choice(name="17:20", value="17:20"),
    app_commands.Choice(name="17:40", value="17:40"),
    app_commands.Choice(name="18:00", value="18:00"),
    app_commands.Choice(name="18:20", value="18:20"),
    app_commands.Choice(name="18:40", value="18:40"),
    app_commands.Choice(name="19:00", value="19:00"),
    app_commands.Choice(name="19:20", value="19:20"),
    app_commands.Choice(name="19:40", value="19:40"),
    app_commands.Choice(name="20:00", value="20:00"),
    app_commands.Choice(name="20:20", value="20:20"),
    app_commands.Choice(name="20:40", value="20:40"),
    app_commands.Choice(name="21:00", value="21:00"),
    app_commands.Choice(name="21:20", value="21:20"),
    app_commands.Choice(name="21:40", value="21:40"),
]


# ===================================================


def is_admin(user: discord.abc.User) -> bool:
    return user.id in ADMIN_IDS


def parse_format(format_text: str) -> int:
    formats = {
        "2x2": 2,
        "3x3": 3,
        "4x4": 4,
        "5x5": 5,
    }

    cleaned = format_text.lower().replace(" ", "").replace("х", "x")

    if cleaned not in formats:
        raise ValueError(
            "Формат должен быть: 2x2, 3x3, 4x4 или 5x5."
        )

    return formats[cleaned]


def get_start_datetime(time_text: str) -> datetime:
    hours_text, minutes_text = time_text.split(":")

    hours = int(hours_text)
    minutes = int(minutes_text)

    now = datetime.now()

    start_time = now.replace(
        hour=hours,
        minute=minutes,
        second=0,
        microsecond=0
    )

    if start_time <= now:
        start_time += timedelta(days=1)

    return start_time


def clean_chat_text(text: str) -> str:
    text = text.lower().strip()

    # Убираем ссылки
    text = re.sub(
        r"https?://\S+|www\.\S+",
        "",
        text
    )

    # Убираем упоминания пользователей, ролей и каналов
    text = re.sub(
        r"<@!?\d+>|<@&\d+>|<#\d+>",
        "",
        text
    )

    # Убираем лишние пробелы
    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


def build_embed(data: dict) -> discord.Embed:
    main_list = "\n".join(
        f"{number}. <@{user_id}>"
        for number, user_id in enumerate(data["main"], start=1)
    ) or "—"

    reserve_list = "\n".join(
        f"{number}. <@{user_id}>"
        for number, user_id in enumerate(data["reserve"], start=1)
    ) or "—"

    embed = discord.Embed(
        title=f"🏹 Стрела | {data['server']}",
        color=discord.Color.green()
    )

    embed.add_field(
        name="Формат",
        value=data["format"],
        inline=True
    )

    embed.add_field(
        name="Время начала",
        value=data["time"],
        inline=True
    )

    embed.add_field(
        name="Против",
        value=data["faction"],
        inline=True
    )

    embed.add_field(
        name="Сторона",
        value=data["side"],
        inline=True
    )

    embed.add_field(
        name="Оружие",
        value=data["weapon"],
        inline=True
    )

    embed.add_field(
        name="Создал",
        value=f"<@{data['creator_id']}>",
        inline=True
    )

    embed.add_field(
        name=f"Основные слоты ({len(data['main'])}/{data['slots_total']})",
        value=main_list,
        inline=False
    )

    embed.add_field(
        name=f"Резерв ({len(data['reserve'])}/3)",
        value=reserve_list,
        inline=False
    )

    embed.set_footer(
        text="Нажми кнопку, чтобы записаться или покинуть слот."
    )

    return embed


class RaidView(ui.View):
    def __init__(self, data: dict):
        super().__init__(timeout=None)

        self.data = data
        self.message = None
        self.lock = asyncio.Lock()

    async def update_message(self):
        if self.message is not None:
            await self.message.edit(
                embed=build_embed(self.data),
                view=self
            )

    @ui.button(
        label="Взять основной слот",
        style=discord.ButtonStyle.green,
        custom_id="main_slot"
    )
    async def main_button(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        user_id = interaction.user.id

        async with self.lock:
            if user_id in self.data["main"]:
                await interaction.response.send_message(
                    "Ты уже записан в основные слоты.",
                    ephemeral=True
                )
                return

            if len(self.data["main"]) >= self.data["slots_total"]:
                await interaction.response.send_message(
                    "Основные слоты заполнены. Можешь записаться в резерв.",
                    ephemeral=True
                )
                return

            was_in_reserve = user_id in self.data["reserve"]

            # Если игрок был в резерве — автоматически удаляем его оттуда
            if was_in_reserve:
                self.data["reserve"].remove(user_id)

            self.data["main"].append(user_id)

            slot_number = len(self.data["main"])

            await interaction.response.defer(ephemeral=True)
            await self.update_message()

            if was_in_reserve:
                text = (
                    f"✅ Ты успешно переведён из резерва в основу.\n"
                    f"Твой номер основного слота: **{slot_number}**.\n"
                    f"Покинуть слот можно кнопкой **«Покинуть слот»**."
                )
            else:
                text = (
                    f"✅ Ты успешно взял основной слот №**{slot_number}**.\n"
                    f"Покинуть слот можно кнопкой **«Покинуть слот»**."
                )

            await interaction.followup.send(
                text,
                ephemeral=True
            )

    @ui.button(
        label="Взять резерв",
        style=discord.ButtonStyle.secondary,
        custom_id="reserve_slot"
    )
    async def reserve_button(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        user_id = interaction.user.id

        async with self.lock:
            if user_id in self.data["reserve"]:
                await interaction.response.send_message(
                    "Ты уже записан в резерв.",
                    ephemeral=True
                )
                return

            if user_id in self.data["main"]:
                await interaction.response.send_message(
                    "Ты уже записан в основные слоты.",
                    ephemeral=True
                )
                return

            if len(self.data["reserve"]) >= 3:
                await interaction.response.send_message(
                    "Резерв заполнен. Максимум: 3 игрока.",
                    ephemeral=True
                )
                return

            self.data["reserve"].append(user_id)

            reserve_number = len(self.data["reserve"])

            await interaction.response.defer(ephemeral=True)
            await self.update_message()

            await interaction.followup.send(
                f"✅ Ты успешно взял резервный слот №**{reserve_number}**.\n"
                f"Покинуть слот можно кнопкой **«Покинуть слот»**.",
                ephemeral=True
            )

    @ui.button(
        label="Покинуть слот",
        style=discord.ButtonStyle.danger,
        custom_id="leave_slot"
    )
    async def leave_button(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        user_id = interaction.user.id

        async with self.lock:
            if user_id in self.data["main"]:
                self.data["main"].remove(user_id)
                place = "основные слоты"

            elif user_id in self.data["reserve"]:
                self.data["reserve"].remove(user_id)
                place = "резерв"

            else:
                await interaction.response.send_message(
                    "Ты не записан в эту стрелу.",
                    ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)
            await self.update_message()

            await interaction.followup.send(
                f"✅ Ты успешно покинул {place}.",
                ephemeral=True
            )


async def get_target_channel():
    channel = bot.get_channel(CHANNEL_ID)

    if channel is None:
        try:
            channel = await bot.fetch_channel(CHANNEL_ID)

        except discord.DiscordException:
            return None

    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return None

    return channel


async def publish_raid(schedule_id: int):
    global last_raid_message_id

    raid = scheduled_raids.get(schedule_id)

    if raid is None:
        return

    seconds_to_wait = (
        raid["publish_time"] - datetime.now()
    ).total_seconds()

    if seconds_to_wait > 0:
        await asyncio.sleep(seconds_to_wait)

    raid = scheduled_raids.get(schedule_id)

    if raid is None:
        return

    data = raid["data"]
    channel = await get_target_channel()

    if channel is None:
        print(
            f"Стрела #{schedule_id} не отправлена: канал недоступен."
        )

        scheduled_raids.pop(schedule_id, None)
        return

    try:
        await channel.send(
            f"@everyone 🏹 Через {NOTIFICATION_BEFORE_MINUTES} минут стрела!\n"
            f"Сервер: **{data['server']}**\n"
            f"Против: **{data['faction']}**\n"
            f"Сторона: **{data['side']}**\n"
            f"Оружие: **{data['weapon']}**\n"
            f"Формат: **{data['format']}**\n"
            f"Время начала: **{data['time']}**",

            allowed_mentions=discord.AllowedMentions(
                everyone=True,
                users=False,
                roles=False
            )
        )

        view = RaidView(data)

        message = await channel.send(
            embed=build_embed(data),
            view=view
        )

        view.message = message

        active_raids[message.id] = {
            "data": data,
            "view": view,
            "message": message
        }

        last_raid_message_id = message.id

    except discord.Forbidden:
        print(
            "У бота нет прав писать в канал "
            "или упоминать @everyone."
        )

    except discord.HTTPException as error:
        print(f"Ошибка Discord: {error}")

    finally:
        scheduled_raids.pop(schedule_id, None)


async def random_chat_loop():
    """
    Раз в случайный промежуток от 30 до 60 минут
    бот отправляет популярную фразу или слово.
    """
    await bot.wait_until_ready()

    while not bot.is_closed():
        delay = random.randint(
            MIN_CHAT_DELAY_SECONDS,
            MAX_CHAT_DELAY_SECONDS
        )

        await asyncio.sleep(delay)

        channel = await get_target_channel()

        if channel is None:
            continue

        # В двух случаях из трёх выбираем фразу
        if phrase_counts and random.choice([True, True, False]):
            popular_phrases = [
                phrase
                for phrase, count in phrase_counts.most_common(30)
            ]

            phrase = random.choice(popular_phrases)

            await channel.send(
                f"💬 {phrase}",
                allowed_mentions=discord.AllowedMentions.none()
            )

        # Если фраз нет — выбираем популярное слово
        elif word_counts:
            popular_words = [
                word
                for word, count in word_counts.most_common(30)
            ]

            word = random.choice(popular_words)

            await channel.send(
                f"💬 {word}",
                allowed_mentions=discord.AllowedMentions.none()
            )


# ----------------- Отслеживание сообщений -----------------


@bot.event
async def on_message(message: discord.Message):
    # Не читаем личные сообщения и сообщения ботов
    if message.guild is None or message.author.bot:
        return

    # Бот анализирует сообщения только в канале стрел
    if message.channel.id == CHANNEL_ID:
        text = clean_chat_text(message.content)

        # Не запоминаем команды
        if text and not text.startswith(("!", "/")):
            words = re.findall(
                r"[a-zа-яё0-9]{3,}",
                text,
                flags=re.IGNORECASE
            )

            # Считаем популярные отдельные слова
            word_counts.update(words)

            # Запоминаем короткие фразы:
            # от 2 до 10 слов и максимум 120 символов
            if 2 <= len(words) <= 10 and len(text) <= 120:
                phrase_counts[text] += 1

    await bot.process_commands(message)


# ----------------- /slot -----------------


@bot.tree.command(
    name="slot",
    description="Запланировать новую стрелу"
)
@app_commands.describe(
    server="Выбери сервер",
    faction="Выбери фракцию противника",
    side="Выбери Attack или Deff",
    weapon="Выбери оружие",
    format="Выбери формат",
    time_str="Выбери время начала стрелы"
)
@app_commands.choices(
    server=SERVER_CHOICES,
    faction=FACTION_CHOICES,
    side=SIDE_CHOICES,
    weapon=WEAPON_CHOICES,
    format=FORMAT_CHOICES,
    time_str=TIME_CHOICES
)
async def slot(
    interaction: Interaction,
    server: app_commands.Choice[str],
    faction: app_commands.Choice[str],
    side: app_commands.Choice[str],
    weapon: app_commands.Choice[str],
    format: app_commands.Choice[str],
    time_str: app_commands.Choice[str]
):
    global next_schedule_id

    # Создание стрел только в ЛС
    if interaction.guild is not None:
        await interaction.response.send_message(
            "Используй команду /slot в личных сообщениях с ботом.",
            ephemeral=True
        )
        return

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "У тебя нет прав для создания стрел.",
            ephemeral=True
        )
        return

    try:
        slots_total = parse_format(format.value)
        start_time = get_start_datetime(time_str.value)

    except ValueError as error:
        await interaction.response.send_message(
            f"Ошибка: {error}",
            ephemeral=True
        )
        return

    publish_time = start_time - timedelta(
        minutes=NOTIFICATION_BEFORE_MINUTES
    )

    # Если до стрелы осталось меньше 30 минут — публикуем сразу
    if publish_time < datetime.now():
        publish_time = datetime.now()

    schedule_id = next_schedule_id
    next_schedule_id += 1

    data = {
        "server": server.value,
        "faction": faction.value,
        "side": side.value,
        "weapon": weapon.value,
        "format": format.value,
        "slots_total": slots_total,
        "time": time_str.value,
        "creator_id": interaction.user.id,
        "main": [],
        "reserve": []
    }

    scheduled_raids[schedule_id] = {
        "data": data,
        "start_time": start_time,
        "publish_time": publish_time,
        "task": None
    }

    task = asyncio.create_task(
        publish_raid(schedule_id)
    )

    scheduled_raids[schedule_id]["task"] = task

    await interaction.response.send_message(
        f"✅ Стрела #{schedule_id} запланирована.\n\n"
        f"Сервер: **{server.value}**\n"
        f"Против: **{faction.value}**\n"
        f"Сторона: **{side.value}**\n"
        f"Оружие: **{weapon.value}**\n"
        f"Формат: **{format.value}**\n"
        f"Начало: **{start_time:%d.%m.%Y %H:%M}**\n"
        f"Уведомление и слоты: **{publish_time:%d.%m.%Y %H:%M}**",
        ephemeral=True
    )


# ----------------- /strels -----------------


@bot.tree.command(
    name="strels",
    description="Показать все запланированные стрелы"
)
async def strels(interaction: Interaction):
    # Нельзя использовать в ЛС
    if interaction.guild is None:
        await interaction.response.send_message(
            "Команду /strels нельзя использовать в личных сообщениях.",
            ephemeral=True
        )
        return

    # Команду может использовать любой участник сервера
    if not scheduled_raids:
        await interaction.response.send_message(
            "📋 Сейчас нет запланированных стрел.",
            ephemeral=False
        )
        return

    lines = []

    for schedule_id, raid in sorted(scheduled_raids.items()):
        data = raid["data"]
        start_time = raid["start_time"]
        publish_time = raid["publish_time"]

        lines.append(
            f"**#{schedule_id}** — "
            f"**{data['server']}** | "
            f"против **{data['faction']}** | "
            f"**{data['side']}** | "
            f"оружие: **{data['weapon']}** | "
            f"**{data['format']}** | "
            f"начало: **{start_time:%d.%m %H:%M}** | "
            f"слоты: **{publish_time:%d.%m %H:%M}**"
        )

    await interaction.response.send_message(
        "📋 **Запланированные стрелы:**\n\n" + "\n".join(lines),
        ephemeral=False
    )


# ----------------- /dstrel -----------------


@bot.tree.command(
    name="dstrel",
    description="Отменить запланированную стрелу"
)
@app_commands.describe(
    number="Номер стрелы из команды /strels"
)
async def dstrel(
    interaction: Interaction,
    number: int
):
    # Отмена стрелы только в ЛС
    if interaction.guild is not None:
        await interaction.response.send_message(
            "Используй команду /dstrel в личных сообщениях с ботом.",
            ephemeral=True
        )
        return

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "У тебя нет прав для отмены стрел.",
            ephemeral=True
        )
        return

    raid = scheduled_raids.get(number)

    if raid is None:
        await interaction.response.send_message(
            f"Стрела #{number} не найдена или уже опубликована.",
            ephemeral=True
        )
        return

    task = raid["task"]

    if task is not None and not task.done():
        task.cancel()

    scheduled_raids.pop(number, None)

    await interaction.response.send_message(
        f"❌ Стрела #{number} отменена.",
        ephemeral=True
    )


# ----------------- /dslot -----------------


@bot.tree.command(
    name="dslot",
    description="Удалить игрока из последней активной стрелы"
)
@app_commands.describe(
    user="Игрок, которого нужно удалить"
)
async def dslot(
    interaction: Interaction,
    user: discord.Member
):
    global last_raid_message_id

    if interaction.guild is None:
        await interaction.response.send_message(
            "Команду /dslot нельзя использовать в личных сообщениях.",
            ephemeral=True
        )
        return

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "У тебя нет прав для использования этой команды.",
            ephemeral=True
        )
        return

    if last_raid_message_id is None:
        await interaction.response.send_message(
            "Сейчас нет активной стрелы.",
            ephemeral=True
        )
        return

    raid = active_raids.get(last_raid_message_id)

    if raid is None:
        await interaction.response.send_message(
            "Активная стрела не найдена.",
            ephemeral=True
        )
        return

    data = raid["data"]
    view = raid["view"]

    async with view.lock:
        if user.id in data["main"]:
            data["main"].remove(user.id)

        elif user.id in data["reserve"]:
            data["reserve"].remove(user.id)

        else:
            await interaction.response.send_message(
                "Этот игрок не записан в слоты.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await view.update_message()

    await interaction.followup.send(
        f"{user.mention} удалён из слотов.",
        ephemeral=True
    )


# ----------------- /addslot -----------------


@bot.tree.command(
    name="addslot",
    description="Добавить игрока в основные слоты"
)
@app_commands.describe(
    user="Игрок, которого нужно добавить"
)
async def addslot(
    interaction: Interaction,
    user: discord.Member
):
    global last_raid_message_id

    if interaction.guild is None:
        await interaction.response.send_message(
            "Команду /addslot нельзя использовать в личных сообщениях.",
            ephemeral=True
        )
        return

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "У тебя нет прав для использования этой команды.",
            ephemeral=True
        )
        return

    if last_raid_message_id is None:
        await interaction.response.send_message(
            "Сейчас нет активной стрелы.",
            ephemeral=True
        )
        return

    raid = active_raids.get(last_raid_message_id)

    if raid is None:
        await interaction.response.send_message(
            "Активная стрела не найдена.",
            ephemeral=True
        )
        return

    data = raid["data"]
    view = raid["view"]

    async with view.lock:
        if user.id in data["main"]:
            await interaction.response.send_message(
                "Этот игрок уже находится в основных слотах.",
                ephemeral=True
            )
            return

        if len(data["main"]) >= data["slots_total"]:
            await interaction.response.send_message(
                "Основные слоты заполнены.",
                ephemeral=True
            )
            return

        if user.id in data["reserve"]:
            data["reserve"].remove(user.id)

        data["main"].append(user.id)

        await interaction.response.defer(ephemeral=True)
        await view.update_message()

    await interaction.followup.send(
        f"{user.mention} добавлен в основные слоты.",
        ephemeral=True
    )


# ----------------- События -----------------


@bot.event
async def on_ready():
    print(f"Бот готов: {bot.user}")

    await bot.change_presence(
        activity=discord.Game(
            name="Пикни слот на стрелу, чудище!"
        )
    )

    synced = await bot.tree.sync()

    print(
        f"Синхронизировано slash-команд: {len(synced)}"
    )

    # Запускаем болталку только один раз
    if not hasattr(bot, "random_chat_task"):
        bot.random_chat_task = asyncio.create_task(
            random_chat_loop()
        )


@bot.event
async def on_app_command_error(
    interaction: Interaction,
    error: app_commands.AppCommandError
):
    print(f"Ошибка slash-команды: {error}")

    if interaction.response.is_done():
        await interaction.followup.send(
            "При выполнении команды произошла ошибка.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "При выполнении команды произошла ошибка.",
            ephemeral=True
        )


if __name__ == "__main__":
    bot.run(TOKEN)