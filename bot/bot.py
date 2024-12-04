# bot/bot.py

import os
import requests
import telebot
from telebot import types
import psycopg2
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
from telebot.apihelper import ApiTelegramException
from datetime import datetime
from pytz import timezone

# Загрузка переменных окружения
load_dotenv()

# Конфигурационные переменные
API_KEY = os.getenv('API_KEY')
CATALOG_ID = os.getenv('CATALOG_ID')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')

# Настройка логирования
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

handler = RotatingFileHandler('bot.log', maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Инициализация Telegram-бота
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Подключение к базе данных PostgreSQL
try:
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
    cursor = conn.cursor()
    logger.info("Успешное подключение к базе данных.")
except Exception as e:
    logger.exception(f"Ошибка при подключении к базе данных: {e}")
    exit(1)

# Функция для отправки сообщения в Yandex GPT
def send_message_to_gpt(message):
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {API_KEY}"
    }

    # Системный промпт
    system_prompt = (
        "Вы — дружелюбный и понимающий помощник для обучающихся. "
        "Отвечай только на вопросы. Не предлагай ничего своего. "
        "Не приветствуй пользователя. "
        "Тебя зовут Эврика. "
        "Не начинай свой ответ с приветствия и со своего имени. "
        "Объясняйте темы простым и понятным языком для детей от 6 до 15 лет. "
        "Используй мотивирующий тон, чтобы ученику было интересно и весело. "
        "Используйте примеры из повседневной жизни, чтобы сделать сложные концепции более доступными и наглядными. "
        "Поддерживайте позитивный тон и иногда добавляйте эмодзи, чтобы сделать общение веселым. "
        "Не отвечай на темы секса, сексуальные темы, порнографию, наркотики, экстремизм, терроризм. Вежливо отказывай."
    )

    payload = {
        "modelUri": f"gpt://{CATALOG_ID}/yandexgpt/rc",
        "completionOptions": {
            "stream": False,
            "temperature": 0.7,
            "maxTokens": 2000
        },
        "messages": [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": message}
        ]
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 200:
        result = response.json()
        text = result['result']['alternatives'][0]['message']['text']
        return text
    else:
        logger.error(f"Ошибка при обращении к Yandex GPT: {response.status_code} - {response.text}")
        return "Извините, произошла ошибка при обработке вашего запроса."

# Вспомогательная функция для записи сообщений в базу данных
def log_message(user_id, role, content, is_command=False):
    try:
        cursor.execute("SELECT id FROM users WHERE telegram_id = %s;", (user_id,))
        user = cursor.fetchone()
        if user:
            user_db_id = user[0]
            cursor.execute("""
                INSERT INTO messages (user_id, role, content)
                VALUES (%s, %s, %s);
            """, (user_db_id, role, content))
            conn.commit()

            if role == 'user':
                today = datetime.now(timezone('Europe/Moscow')).date()
                cursor.execute("SELECT id, command_count, message_count FROM user_statistics WHERE date = %s;", (today,))
                stat = cursor.fetchone()
                if stat:
                    stat_id, cmd_count, msg_count = stat
                    if is_command:
                        cmd_count += 1
                    else:
                        msg_count += 1
                    cursor.execute("""
                        UPDATE user_statistics
                        SET command_count = %s, message_count = %s
                        WHERE id = %s;
                    """, (cmd_count, msg_count, stat_id))
                else:
                    cursor.execute("""
                        INSERT INTO user_statistics (date, user_count, command_count, message_count)
                        VALUES (%s, 0, %s, %s);
                    """, (today, 1 if is_command else 0, 1 if not is_command else 0))
                conn.commit()
    except Exception as e:
        logger.exception(f"Ошибка при записи сообщения: {e}")

# Вспомогательная функция для получения или создания пользователя
def get_or_create_user(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name

    cursor.execute("SELECT id, is_banned FROM users WHERE telegram_id = %s;", (user_id,))
    user = cursor.fetchone()
    if user:
        return user[0], user[1]  # user_db_id, is_banned
    else:
        cursor.execute("""
            INSERT INTO users (telegram_id, username, first_name, last_name)
            VALUES (%s, %s, %s, %s) RETURNING id;
        """, (user_id, username, first_name, last_name))
        user_db_id = cursor.fetchone()[0]
        conn.commit()
        # Обновляем статистику
        today = datetime.now(timezone('Europe/Moscow')).date()
        cursor.execute("SELECT user_count FROM user_statistics WHERE date = %s;", (today,))
        stat = cursor.fetchone()
        if stat:
            cursor.execute("UPDATE user_statistics SET user_count = user_count + 1 WHERE date = %s;", (today,))
        else:
            cursor.execute("INSERT INTO user_statistics (date, user_count, command_count, message_count) VALUES (%s, 1, 0, 0);", (today,))
        conn.commit()
        return user_db_id, False

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id

    user_db_id, is_banned = get_or_create_user(message)

    if is_banned:
        try:
            bot.send_message(message.chat.id, "Извините, Вы не можете воспользоваться Эврикой.")
        except ApiTelegramException as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
        return

    # Создаем инлайн-клавиатуру с кнопками "Да" и "Нет"
    keyboard = types.InlineKeyboardMarkup()
    yes_button = types.InlineKeyboardButton(text="Да", callback_data="accept_terms")
    no_button = types.InlineKeyboardButton(text="Нет", callback_data="decline_terms")
    keyboard.add(yes_button, no_button)

    # Отправляем сообщение с соглашением и клавиатурой
    try:
        bot.send_message(
            message.chat.id,
            "Пожалуйста, перед тем, как начать наше образовательное путешествие, прочитайте пользовательское соглашение.\nhttps://edpalm.academy/usloviya-predostavleniya-servisa",
            reply_markup=keyboard
        )
    except ApiTelegramException as e:
        logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")

# Обработчик нажатий на инлайн-кнопки
@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    user_id = call.from_user.id

    cursor.execute("SELECT id, is_banned FROM users WHERE telegram_id = %s;", (user_id,))
    user = cursor.fetchone()
    if not user:
        logger.error(f"Пользователь с telegram_id={user_id} не найден.")
        return
    user_db_id, is_banned = user

    if is_banned:
        try:
            bot.send_message(call.message.chat.id, "Извините, Вы не можете воспользоваться Эврикой.")
        except ApiTelegramException as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
        return

    if call.data == "accept_terms":
        try:
            response_text = (
                "Дорогой ученик, перед тобой виртуальный помощник образования. "
                "Чтобы ознакомиться с моими возможностями, нажми на кнопку «Меню»."
            )
            bot.send_message(call.message.chat.id, response_text)
            log_message(user_id, 'bot', response_text)
            # Принудительно вызываем команду /subject
            handle_subject_command(call.message)
        except ApiTelegramException as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
    elif call.data == "decline_terms":
        handle_start(call.message)
    elif call.data.startswith("subject_"):
        # Пользователь выбрал предмет
        subject = call.data[len("subject_"):]
        # Сохраняем выбранный предмет в базе данных
        try:
            cursor.execute("""
                UPDATE users SET last_subject = %s WHERE id = %s;
            """, (subject, user_db_id))
            conn.commit()

            response_text = f"Теперь я буду отвечать на вопросы, связанные с предметом: {subject}"
            bot.send_message(call.message.chat.id, response_text)
            log_message(user_id, 'bot', response_text)
        except Exception as e:
            logger.exception(f"Ошибка при сохранении предмета для пользователя {user_id}: {e}")
    else:
        pass  # Обработка других случаев, если необходимо

# Обработчик команды /faq
@bot.message_handler(commands=['faq'])
def handle_faq(message):
    user_id = message.from_user.id

    cursor.execute("SELECT is_banned FROM users WHERE telegram_id = %s;", (user_id,))
    user = cursor.fetchone()
    if not user:
        logger.error(f"Пользователь с telegram_id={user_id} не найден.")
        return
    is_banned = user[0]
    if is_banned:
        try:
            bot.send_message(message.chat.id, "Извините, Вы не можете воспользоваться Эврикой.")
        except ApiTelegramException as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
        return

    faq_text = """1) Говори точно, что именно тебе нужно:
    Например, вместо «Помоги с математикой», лучше сказать «Как решить пример: 3 умножить на 2?». Это поможет мне точно понять, что именно тебе нужно.
    2) Задавай по одному вопросу:
    Если хочешь узнать не только о животных, но и о том, как решать математические примеры, лучше спросить сначала одно, а потом другое. Например, сначала спроси «Что едят зайцы?» и после ответа спроси «Как сложить 5 и 3?»
    3) Проверяй, что написал/-а:
    Если пишешь пример или вопрос, убедись, что в нём нет орфографических ошибок. Например, если хочешь спросить про «5 умножить на 2», не пиши «5 ужножить на 2», потому что я могу не понять вопрос.
    4) Спрашивай, если что-то непонятно:
    Если я объяснила, как решить пример, и тебе что-то непонятно, спроси меня еще раз. Например, я уже рассказала информацию на тему: «Что едят зайцы?», а ты хочешь узнать подробности. Тогда спроси меня, к примеру, «А что именно едят зайцы весной?»
    5) Задавай мне много вопросов:
    Я всегда рада ответить на любой твой вопрос. Задавай интересующие вопросы снова и снова, ведь учиться – это очень интересно!"""
    try:
        bot.send_message(message.chat.id, faq_text)
        # Логируем сообщение как команду
        log_message(user_id, 'user', '/faq', is_command=True)
        log_message(user_id, 'bot', faq_text)
    except ApiTelegramException as e:
        logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")

# Обработчик команды /feedback
@bot.message_handler(commands=['feedback'])
def handle_feedback(message):
    user_id = message.from_user.id

    cursor.execute("SELECT is_banned FROM users WHERE telegram_id = %s;", (user_id,))
    user = cursor.fetchone()
    if not user:
        logger.error(f"Пользователь с telegram_id={user_id} не найден.")
        return
    is_banned = user[0]
    if is_banned:
        try:
            bot.send_message(message.chat.id, "Извините, Вы не можете воспользоваться Эврикой.")
        except ApiTelegramException as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
        return

    feedback_text = """У тебя появились вопросы, пожелания, или ты заметил/-а какую-то ошибку? Давай вместе улучшим Эврику!
Напиши нам на почту:
evrika@hss.center"""
    try:
        bot.send_message(message.chat.id, feedback_text)
        # Логируем сообщение как команду
        log_message(user_id, 'user', '/feedback', is_command=True)
        log_message(user_id, 'bot', feedback_text)
    except ApiTelegramException as e:
        logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")

# Обработчик команды /help
@bot.message_handler(commands=['help'])
def handle_help(message):
    user_id = message.from_user.id

    cursor.execute("SELECT is_banned FROM users WHERE telegram_id = %s;", (user_id,))
    user = cursor.fetchone()
    if not user:
        logger.error(f"Пользователь с telegram_id={user_id} не найден.")
        return
    is_banned = user[0]
    if is_banned:
        try:
            bot.send_message(message.chat.id, "Извините, Вы не можете воспользоваться Эврикой.")
        except ApiTelegramException as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
        return

    help_text = """Список доступных команд:
/start - Начать работу с ботом
/faq - Как со мной общаться?
/subject - Выбрать предмет
/feedback - Обратная связь
/help - Список команд"""
    try:
        bot.send_message(message.chat.id, help_text)
        # Логируем сообщение как команду
        log_message(user_id, 'user', '/help', is_command=True)
        log_message(user_id, 'bot', help_text)
    except ApiTelegramException as e:
        logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")

# Обработчик команды /subject
@bot.message_handler(commands=['subject'])
def handle_subject_command(message):
    user_id = message.from_user.id

    cursor.execute("SELECT id, is_banned FROM users WHERE telegram_id = %s;", (user_id,))
    user = cursor.fetchone()
    if not user:
        logger.error(f"Пользователь с telegram_id={user_id} не найден.")
        return
    user_db_id, is_banned = user

    if is_banned:
        try:
            bot.send_message(message.chat.id, "Извините, Вы не можете воспользоваться Эврикой.")
        except ApiTelegramException as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
        return

    # Создаем инлайн-клавиатуру с предметами
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    subjects = [
        "Алгебра", "Русский язык", "Английский язык", "География",
        "Информатика", "Обществознание", "Окружающий мир", "Геометрия",
        "Литература", "Биология", "История", "Физика",
        "Химия", "Математика"
    ]
    buttons = [types.InlineKeyboardButton(text=subj, callback_data=f"subject_{subj}") for subj in subjects]
    keyboard.add(*buttons)

    try:
        bot.send_message(
            message.chat.id,
            "Пожалуйста, выбери необходимый предмет. Ознакомиться со всеми моими возможностями можно, нажав на кнопку «Меню».",
            reply_markup=keyboard
        )
        # Логируем сообщение как команду
        log_message(user_id, 'user', '/subject', is_command=True)
    except ApiTelegramException as e:
        logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")

# Обработчик всех текстовых сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id

    cursor.execute("SELECT id, is_banned FROM users WHERE telegram_id = %s;", (user_id,))
    user = cursor.fetchone()
    if not user:
        logger.error(f"Пользователь с telegram_id={user_id} не найден.")
        return
    user_db_id, is_banned = user

    if is_banned:
        try:
            bot.send_message(message.chat.id, "Извините, Вы не можете воспользоваться Эврикой.")
        except ApiTelegramException as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
        return

    # Проверяем, выбран ли предмет у пользователя
    try:
        cursor.execute("SELECT last_subject FROM users WHERE id = %s;", (user_db_id,))
        result = cursor.fetchone()

        if result and result[0]:
            # Если предмет выбран, отправляем сообщение в Yandex GPT
            user_message = message.text

            # Логируем сообщение пользователя как обычное сообщение
            log_message(user_id, 'user', user_message, is_command=False)

            try:
                gpt_response = send_message_to_gpt(user_message)
                bot.send_message(message.chat.id, gpt_response)
                # Логируем ответ бота
                log_message(user_id, 'bot', gpt_response)
            except ApiTelegramException as e:
                if e.error_code == 403:
                    logger.info(f"Пользователь {user_id} заблокировал бота.")
                else:
                    logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
            except Exception as e:
                logger.exception(f"Произошла ошибка при обработке сообщения от пользователя {user_id}: {e}")
                bot.send_message(message.chat.id, "Извините, произошла ошибка при обработке вашего сообщения.")
        else:
            # Если предмет не выбран, повторяем соглашение
            handle_start(message)
    except Exception as e:
        logger.exception(f"Ошибка при работе с базой данных для пользователя {user_id}: {e}")
        bot.send_message(message.chat.id, "Извините, произошла ошибка при обращении к базе данных.")
