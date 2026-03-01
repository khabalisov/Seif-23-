import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.utils import get_random_id
import sqlite3
import datetime
import threading
import time
import math

# Конфигурация
TOKEN = "vk1.a.0euN8jV1vl33Ez4XURp9fO1HbXcn1LUmKbu03e2WqRf9LwWB-m3Qfn9jsink_KK4vRqoFgq0oS5e-AYteFGt7Kh9dn5DZ9u-T13fo6con8LT_G-HSkB6V-ErmLlaT0z5YD8n9H0V5f5sJCqYfYTqx8f66OoXTYGZFVefIDPB8yLa-fdPK4eoK6w9hmWfmxLQXTV3Rt8LVYg-0t76fSjVaA"
GROUP_ID = "195388835"
SECRET_CODE = "3461695"  # Загаданный код

# Инициализация бота
vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)


# База данных
def init_db():
    conn = sqlite3.connect('game.db')
    c = conn.cursor()

    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  attempts INTEGER DEFAULT 0,
                  total_attempts INTEGER DEFAULT 0,
                  last_attempt_date TEXT,
                  guessed_numbers TEXT DEFAULT '',
                  last_hint_total INTEGER DEFAULT 0,
                  game_active INTEGER DEFAULT 0,
                  last_hint_date TEXT)''')

    # Таблица для глобального статуса игры
    c.execute('''CREATE TABLE IF NOT EXISTS game_status
                 (id INTEGER PRIMARY KEY CHECK (id = 1),
                  is_solved INTEGER DEFAULT 0,
                  winner_id INTEGER,
                  winner_name TEXT,
                  solved_date TEXT,
                  secret_code TEXT)''')

    # Вставляем начальную запись, если её нет
    c.execute("INSERT OR IGNORE INTO game_status (id, is_solved, secret_code) VALUES (1, 0, ?)", (SECRET_CODE,))

    conn.commit()
    conn.close()


init_db()


# Функции для работы с БД
def get_user_data(user_id):
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    data = c.fetchone()
    conn.close()
    return data


def update_user_data(user_id, **kwargs):
    conn = sqlite3.connect('game.db')
    c = conn.cursor()

    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if c.fetchone() is None:
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))

    for key, value in kwargs.items():
        c.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (value, user_id))

    conn.commit()
    conn.close()


def get_game_status():
    """Получает глобальный статус игры"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute("SELECT is_solved, winner_id, winner_name, solved_date, secret_code FROM game_status WHERE id = 1")
    data = c.fetchone()
    conn.close()
    return data


def set_game_solved(winner_id, winner_name):
    """Устанавливает игру как решенную"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute("""
        UPDATE game_status 
        SET is_solved = 1, 
            winner_id = ?, 
            winner_name = ?, 
            solved_date = ? 
        WHERE id = 1
    """, (winner_id, winner_name, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()


def reset_game():
    """Сбрасывает игру для нового раунда"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()

    # Сбрасываем статус игры
    c.execute(
        "UPDATE game_status SET is_solved = 0, winner_id = NULL, winner_name = NULL, solved_date = NULL WHERE id = 1")

    # Очищаем прогресс всех пользователей
    c.execute(
        "UPDATE users SET game_active = 0, attempts = 0, total_attempts = 0, guessed_numbers = '', last_hint_total = 0")

    conn.commit()
    conn.close()


def check_game_active():
    """Проверяет, активна ли игра"""
    game_status = get_game_status()
    return game_status[0] == 0  # is_solved = 0 значит игра активна


def get_winner_info():
    """Получает информацию о победителе"""
    game_status = get_game_status()
    if game_status[0] == 1:
        return {
            'winner_id': game_status[1],
            'winner_name': game_status[2],
            'solved_date': game_status[3]
        }
    return None


def reset_daily_attempts():
    """Сброс попыток каждый день"""
    while True:
        now = datetime.datetime.now()
        tomorrow = now.replace(hour=0, minute=0, second=1) + datetime.timedelta(days=1)
        sleep_seconds = (tomorrow - now).seconds
        time.sleep(sleep_seconds)

        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute("UPDATE users SET attempts = 0")
        conn.commit()
        conn.close()

        print(f"Попытки сброшены {datetime.datetime.now()}")


# Запуск сброса попыток
threading.Thread(target=reset_daily_attempts, daemon=True).start()


def check_previous_attempt(user_id, code):
    """Проверяет, использовал ли пользователь этот код ранее"""
    user_data = get_user_data(user_id)
    if user_data and user_data[4]:  # guessed_numbers
        guessed = user_data[4].split(',')
        return code in guessed
    return False


def get_hint(guess_code):
    """Генерирует подсказку в формате *6*6**"""
    hint = []
    for i in range(7):
        if guess_code[i] == SECRET_CODE[i]:
            hint.append(guess_code[i])
        else:
            hint.append('*')
    return ''.join(hint)


def can_use_hint(user_data):
    """Проверяет, доступна ли подсказка"""
    total_attempts = user_data[2]  # total_attempts
    last_hint_total = user_data[5]  # last_hint_total

    # Подсказка доступна каждые 25 попыток
    next_hint_threshold = ((last_hint_total // 25) + 1) * 25
    return total_attempts >= next_hint_threshold


def get_next_hint_threshold(user_data):
    """Возвращает номер попытки, когда будет доступна следующая подсказка"""
    total_attempts = user_data[2]
    last_hint_total = user_data[5]

    next_hint = ((last_hint_total // 25) + 1) * 25
    if next_hint <= total_attempts:
        next_hint = ((total_attempts // 25) + 1) * 25

    return next_hint


def get_user_name(user_id):
    """Получает имя пользователя ВК"""
    try:
        user = vk.users.get(user_ids=user_id)[0]
        return f"{user['first_name']} {user['last_name']}"
    except:
        return f"id{user_id}"


def send_message(user_id, message):
    """Отправка сообщения пользователю"""
    try:
        vk.messages.send(
            user_id=user_id,
            random_id=get_random_id(),
            message=message
        )
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")


def broadcast_message(message):
    """Рассылает сообщение всем активным игрокам"""
    try:
        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE game_active = 1")
        active_users = c.fetchall()
        conn.close()

        for user in active_users:
            try:
                send_message(user[0], message)
            except:
                pass
    except Exception as e:
        print(f"Ошибка рассылки: {e}")


# Основной цикл обработки сообщений
print("Бот запущен. Ожидание сообщений...")
print(f"Загаданный код: {SECRET_CODE}")

for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        message = event.text.strip()
        message_lower = message.lower()

        # Проверяем, активна ли игра
        game_active = check_game_active()

        # Команда для администратора (сброс игры)
        if message_lower == "!сбросить игру" and user_id in [123456789]:  # Замените на свой ID
            reset_game()
            broadcast_message("🔄 ИГРА ПЕРЕЗАПУЩЕНА! Загадан новый код! Все могут начинать игру заново!")
            send_message(user_id, "✅ Игра успешно сброшена")
            continue

        # Если игра уже завершена
        if not game_active and message_lower != "статистика" and message_lower != "помощь":
            winner = get_winner_info()
            if winner:
                winner_text = f"Победитель: {winner['winner_name']}"
                solved_time = datetime.datetime.fromisoformat(winner['solved_date']).strftime("%d.%m.%Y %H:%M")
            else:
                winner_text = "Неизвестный победитель"
                solved_time = "неизвестно"

            response = f"""
🔒 ИГРА ЗАВЕРШЕНА 🔒

Код уже взломан!
{winner_text}
Дата победы: {solved_time}

Следующая игра начнется позже.
Следите за новостями сообщества!
            """
            send_message(user_id, response)
            continue

        # Команда начала игры
        if message_lower == "подключиться к сети":
            user_data = get_user_data(user_id)

            # Активируем игру для пользователя
            update_user_data(
                user_id,
                game_active=1,
                attempts=0,
                total_attempts=0,
                guessed_numbers='',
                last_hint_total=0
            )

            welcome_msg = """
🤖 ПОДКЛЮЧЕНИЕ К СЕТИ УСТАНОВЛЕНО 🔐

Добро пожаловать в игру Ранер"!
Нам нужно вскрыть код из 7 цифр. Сможешь его взломать?

Правила игры:
• В день даётся 20 попыток
• Подсказка доступна каждые 25 попыток
• Повторные попытки не сгорают, но и не засчитываются
• Победитель будет только один!

Команды:
• Отправь 7 цифр - попытка взлома
• Взлом XXXXXXX - подсказка
• статистика - твоя статистика

Удачи!Чумба!
            """
            send_message(user_id, welcome_msg)

        # Команда подсказки
        elif message_lower.startswith("взлом"):
            parts = message.split()
            if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 7:
                guess_code = parts[1]

                user_data = get_user_data(user_id)

                # Проверяем, активна ли игра для пользователя
                if not user_data or user_data[6] != 1:  # game_active
                    send_message(user_id, "⛔ Чумба подключись к сети! Напиши 'Подключиться к сети'")
                    continue

                # Проверяем доступность подсказки
                if can_use_hint(user_data):
                    # Генерируем подсказку
                    hint_result = get_hint(guess_code)

                    # Обновляем информацию о последней использованной подсказке
                    update_user_data(
                        user_id,
                        last_hint_total=user_data[2],  # текущее total_attempts
                        last_hint_date=datetime.datetime.now().isoformat()
                    )

                    response = f"🔓 ВЗЛОМ: {hint_result}"
                    send_message(user_id, response)

                    # Проверяем, может это была победная попытка
                    if guess_code == SECRET_CODE:
                        winner_name = get_user_name(user_id)

                        # Устанавливаем победителя
                        set_game_solved(user_id, winner_name)

                        win_msg = f"""
🎉 ПОБЕДА! КОД ВЗЛОМАН! 🎉

Поздравляю, {winner_name}!
Ты первый и единственный, кто взломал сейф!

Игра завершена. Спасибо всем за участие!
                        """

                        # Отправляем сообщение победителю
                        send_message(user_id, win_msg)

                        # Рассылаем всем остальным игрокам о завершении игры
                        broadcast_message(f"""
🔒 ИГРА ЗАВЕРШЕНА 🔒

Код взломан!
Победитель: {winner_name}

Следующая игра начнется позже.
Следите за новостями!
                        """)

                        # Деактивируем игру для всех
                        conn = sqlite3.connect('game.db')
                        c = conn.cursor()
                        c.execute("UPDATE users SET game_active = 0")
                        conn.commit()
                        conn.close()
                else:
                    next_hint = get_next_hint_threshold(user_data)
                    remaining = next_hint - user_data[2]
                    response = f"⛔ Следующая подсказка будет доступна через {remaining} попыток (после {next_hint} попытки)"
                    send_message(user_id, response)
            else:
                send_message(user_id, "❌ Неверный формат! Используй: Взлом 1234567")

        # Проверка на попытку взлома (7 цифр)
        elif message.isdigit() and len(message) == 7:
            user_data = get_user_data(user_id)

            # Проверяем, активна ли игра для пользователя
            if not user_data or user_data[6] != 1:  # game_active
                send_message(user_id, "⛔ Сначала начни игру! Напиши 'Подключиться к сети'")
                continue

            current_attempts = user_data[1]  # attempts (дневные)
            total_attempts = user_data[2]  # total_attempts (всего)

            # Проверяем лимит попыток на сегодня
            if current_attempts >= 20:
                send_message(user_id, "⛔ У тебя закончились попытки на сегодня! Возвращайся завтра!")
                continue

            # Проверяем, не использовал ли уже этот код
            if check_previous_attempt(user_id, message):
                response = f"🤖 Чумба, ты уже пытался использовать этот код!"
                send_message(user_id, response)
                continue

            # Сохраняем попытку
            guessed = user_data[4] if user_data[4] else ""

            if guessed:
                new_guessed = f"{guessed},{message}"
            else:
                new_guessed = message

            # Обновляем счетчики
            new_attempts = current_attempts + 1
            new_total = total_attempts + 1

            # Проверяем код
            if message == SECRET_CODE:
                winner_name = get_user_name(user_id)

                # Устанавливаем победителя
                set_game_solved(user_id, winner_name)

                win_msg = f"""
🎉 ПОБЕДА! КОД ВЗЛОМАН! 🎉

Поздравляю, {winner_name}!
Ты первый и единственный, кто взломал сейф!
Код: {SECRET_CODE}

Игра завершена. Спасибо всем за участие!
                """

                # Отправляем сообщение победителю
                send_message(user_id, win_msg)

                # Рассылаем всем остальным игрокам о завершении игры
                broadcast_message(f"""
🔒 ИГРА ЗАВЕРШЕНА 🔒

Код взломан!
Победитель: {winner_name}

Следующая игра начнется позже.
Следите за новостями сообщества!
                """)

                # Деактивируем игру для всех
                conn = sqlite3.connect('game.db')
                c = conn.cursor()
                c.execute("UPDATE users SET game_active = 0")
                conn.commit()
                conn.close()
            else:
                # Проверяем доступность подсказки
                remaining_attempts = 20 - new_attempts

                # Обновляем данные пользователя
                update_user_data(
                    user_id,
                    attempts=new_attempts,
                    total_attempts=new_total,
                    guessed_numbers=new_guessed
                )

                # Получаем обновленные данные для проверки подсказки
                user_data_updated = get_user_data(user_id)

                hint_status = ""
                if can_use_hint(user_data_updated):
                    hint_status = "\n💡 Тебе доступна подсказка! Напиши 'Взлом XXXXXXX'"
                else:
                    next_hint = get_next_hint_threshold(user_data_updated)
                    if next_hint > new_total:
                        hint_status = f"\n💡 Следующая подсказка через {next_hint - new_total} попыток"

                response = f"❌ Неверный код! Осталось попыток: {remaining_attempts}{hint_status}"
                send_message(user_id, response)

        # Статистика
        elif message_lower == "статистика":
            game_status = get_game_status()
            user_data = get_user_data(user_id)

            if game_status[0] == 1:
                winner_text = f"\n🏆 ПОБЕДИТЕЛЬ: {game_status[2]}"
            else:
                winner_text = "\n🔓 ИГРА АКТИВНА"

            if user_data:
                attempts_left = 20 - user_data[1]
                total_attempts = user_data[2]

                next_hint = get_next_hint_threshold(user_data)
                hints_used = user_data[5] // 25

                if can_use_hint(user_data):
                    hint_status = "✅ Доступна сейчас!"
                else:
                    hint_status = f"❌ Будет через {next_hint - total_attempts} попыток"

                stat_msg = f"""
📊 ТВОЯ СТАТИСТИКА:{winner_text}
• Попыток сегодня: {user_data[1]}/20
• Осталось попыток: {attempts_left}
• Всего попыток: {total_attempts}
• Использовано подсказок: {hints_used}
• Следующая подсказка: {hint_status}
• Игра активна: {"✅ Да" if user_data[6] == 1 else "❌ Нет"}
                """
            else:
                stat_msg = f"""
📊 ТВОЯ СТАТИСТИКА:{winner_text}
Ты еще не начинал игру!
Напиши 'Подключиться к сети'
                """

            send_message(user_id, stat_msg)

        # Помощь
        elif message_lower in ["помощь", "help", "команды"]:
            help_msg = """
🔐 ИГРА "ВЗЛОМ СЕЙФА" - ПОМОЩЬ:

🚀 Начать игру:
Подключиться к сети

🎮 Правила:
• Код состоит из 7 цифр
• В день 20 попыток
• Подсказка каждые 25 попыток
• Повторные коды не засчитываются
• Победитель будет только один!

📝 Команды:
• 1234567 - попытка взлома
• Взлом 1234567 - подсказка
• статистика - твоя статистика
• помощь - это сообщение

Пример подсказки:
Взлом 1234567 -> *2*4**7

Удачи в взломе! 🍀
            """
            send_message(user_id, help_msg)

        # Приветствие для новых
        elif message_lower in ["Хаюшки", "Hi", "привет", "Салют"]:
            hello_msg = """
👋 Привет! Я Ребека нужна помощь в взломе сейфа!.

Чтобы начать игру, напиши:
Подключиться к сети

Или напиши "помощь" для получения инструкций.
            """
            send_message(user_id, hello_msg)

        # Неизвестная команда
        elif message:

            send_message(user_id, "🤖 Неизвестная команда. Напиши 'помощь' для списка команд.")
