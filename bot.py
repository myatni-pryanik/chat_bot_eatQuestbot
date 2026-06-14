import asyncio
import os
import re
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

import database as db  # Файл database.py должен быть в той же папке

# Настройка логирования для отслеживания событий в консоли
logging.basicConfig(level=logging.INFO)

load_dotenv()

# Инициализация бота
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    exit("ОШИБКА: Токен бота не найден. Проверь файл .env")

bot = Bot(token=TOKEN)
dp = Dispatcher()
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID")

# --- СОСТОЯНИЯ (FSM) ---
class AddPlace(StatesGroup):
    waiting_for_name = State()
    waiting_for_type = State()
    waiting_for_metro = State()
    waiting_for_address = State()
    waiting_for_photo = State()
    waiting_for_confirm = State()

class SearchStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_budget = State()
    waiting_for_metro = State()
    waiting_for_cuisine = State() # Только для ресторанов

# --- МЕНЮ ---
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="🔍 Поиск"), types.KeyboardButton(text="⭐ Избранное"))
    builder.row(types.KeyboardButton(text="➕ Добавить новое место"))
    return builder.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    # Регистрируем пользователя в БД
    db.register_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )
    
    logging.info(f"Пользователь {message.from_user.id} зарегистрирован и нажал start")
    await message.answer(
        "Привет! Теперь ты в базе. Можешь искать заведения и добавлять их в избранное! ✨",
        reply_markup=main_menu()
    )

# 1. Нажатие на главную кнопку "Поиск"
# 1. Шаг: Выбор категории (Ресторан / Кофейня)
@dp.message(F.text == "🔍 Поиск")
async def search_start(message: types.Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="🍴 Рестораны", callback_data="search_restaurant"))
    builder.add(types.InlineKeyboardButton(text="☕️ Кофейни", callback_data="search_cafe"))
    
    await state.set_state(SearchStates.waiting_for_category)
    await message.answer("Что именно ты ищешь?", reply_markup=builder.as_markup())

# 2. Шаг: Выбор бюджета
@dp.callback_query(SearchStates.waiting_for_category)
async def choose_category(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[1]
    await state.update_data(category=category)
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="$ (Дешево)", callback_data="budget_1"))
    builder.add(types.InlineKeyboardButton(text="$$ (Средне)", callback_data="budget_2"))
    builder.add(types.InlineKeyboardButton(text="$$$ (Дорого)", callback_data="budget_3"))
    builder.add(types.InlineKeyboardButton(text="Пропустить ➡️", callback_data="budget_skip"))
    
    await state.set_state(SearchStates.waiting_for_budget)
    await callback.message.edit_text("Выбери бюджет:", reply_markup=builder.as_markup())
    await callback.answer()

# --- ШАГ 3: ВЫБОР МЕТРО (КНОПКАМИ ИЗ БД) ---
@dp.callback_query(SearchStates.waiting_for_budget)
async def choose_budget(callback: types.CallbackQuery, state: FSMContext):
    # Сохраняем выбранный бюджет
    budget = None if "skip" in callback.data else int(callback.data.split("_")[1])
    await state.update_data(budget=budget)
    
    # 1. Тянем динамический список станций из БД
    stations = db.get_all_metro() 
    
    builder = InlineKeyboardBuilder()
    for s in stations:
        # Важно: используем ID из базы для callback_data
        builder.add(types.InlineKeyboardButton(
            text=s['name'], 
            callback_data=f"metro_{s['id']}"
        ))
    
    builder.add(types.InlineKeyboardButton(text="Везде 🌍", callback_data="metro_skip"))
    builder.adjust(2) 
    
    await state.set_state(SearchStates.waiting_for_metro)
    await callback.message.edit_text("Выбери район (метро):", reply_markup=builder.as_markup())
    await callback.answer()

# --- ШАГ 4: КУХНЯ (КНОПКАМИ ИЗ БД) ---
@dp.callback_query(SearchStates.waiting_for_metro)
async def choose_metro(callback: types.CallbackQuery, state: FSMContext):
    # Теперь здесь сохраняем ID (приводим к int, если не skip)
    metro_id = None if "skip" in callback.data else int(callback.data.replace("metro_", ""))
    await state.update_data(metro_id=metro_id)
    
    data = await state.get_data()

    # Если кофейня — пропускаем кухню
    if data.get('category') == 'cafe':
        await callback.message.edit_text("☕️ Ищу подходящие кофейни...")
        return await finish_search_and_show_results(callback.message, state)

    # 2. Тянем динамический список кухонь из БД
    cuisines = db.get_all_cuisines()
    
    builder = InlineKeyboardBuilder()
    for c in cuisines:
        builder.add(types.InlineKeyboardButton(
            text=c['name'], 
            callback_data=f"cuisine_{c['id']}"
        ))
        
    builder.add(types.InlineKeyboardButton(text="Любая кухня 🍕", callback_data="cuisine_skip"))
    builder.adjust(2)

    await state.set_state(SearchStates.waiting_for_cuisine)
    await callback.message.edit_text("Какую кухню предпочитаешь?", reply_markup=builder.as_markup())
    await callback.answer()

# 5. ШАГ: КУХНЯ (Добавь это!)
@dp.callback_query(SearchStates.waiting_for_cuisine)
async def choose_cuisine(callback: types.CallbackQuery, state: FSMContext):
    cuisine_id = None if "skip" in callback.data else int(callback.data.replace("cuisine_", ""))
    await state.update_data(cuisine_id=cuisine_id)
    
    await callback.message.edit_text("🔍 Ищу лучшие заведения...")
    await finish_search_and_show_results(callback.message, state)
    await callback.answer()

async def finish_search_and_show_results(message: types.Message, state: FSMContext):
    # Получаем все накопленные фильтры
    data = await state.get_data()
    # СРАЗУ очищаем состояние, чтобы пользователь мог пользоваться меню дальше
    await state.clear()
    
    # Вызываем функцию из database.py
    places = db.get_places(
        category=data.get('category'),
        budget=data.get('budget'),
        metro_id=data.get('metro_id'),
        cuisine_id=data.get('cuisine_id')
    )
    
    if not places:
        await message.answer("К сожалению, ничего не нашлось по таким фильтрам 😿", reply_markup=main_menu())
        return

    await message.answer(f"Нашел для тебя заведений: {len(places)}", reply_markup=main_menu())
    
    # Выводим карточки заведений (не более 5)
    for place in places[:5]:
        # Проверяем наличие ссылки, если нет — даем заглушку
        link = place.get('url') or place.get('link') or "https://t.me/EatQuestbot"
        metro_obj = place.get('metro_stations')
        metro_name = metro_obj.get('name') if metro_obj else "Не указано"

        cuisine_obj = place.get('cuisines')
        cuisine_name = cuisine_obj.get('name') if cuisine_obj else "Не указана"
        
        caption = (
            f"<b>{place['name']}</b>\n"
            f"🚇 Метро: {metro_name}\n"
            f"🍴 Кухня: {cuisine_name}\n"
            f"📍 Адрес: {place['address']}\n"
            f"⭐️ Рейтинг: {place.get('rating_cache', 0)}\n"
            f"💰 Бюджет: {'$' * place['budget_level'] if place.get('budget_level') else 'Не указан'}\n\n"
            f"🔗 <a href='{link}'>Перейти на сайт</a>"
        )
        
        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(text="❤️ В избранное", callback_data=f"fav_{place['id']}"))
        
        # Отправляем фото или текст, если фото нет
        if place.get('photo_url'):
            try:
                await message.answer_photo(
                    photo=place['photo_url'],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=builder.as_markup()
                )
            except Exception as e:
                logging.error(f"Ошибка отправки фото: {e}")
                await message.answer(caption, parse_mode="HTML", reply_markup=builder.as_markup())
        else:
            await message.answer(caption, parse_mode="HTML", reply_markup=builder.as_markup())
# --- БЛОК ИЗБРАННОГО ---

# 1. Обработка нажатия кнопки "❤️ В избранное" под карточкой
@dp.callback_query(F.data.startswith("fav_"))
async def add_to_favorites_handler(callback: types.CallbackQuery):
    # Извлекаем ID места из callback_data (например, "fav_12")
    place_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    try:
        db.add_to_favorites(user_id, place_id)
        await callback.answer("✅ Добавлено в избранное!", show_alert=False)
    except Exception as e:
        logging.error(f"Ошибка добавления в избранное: {e}")
        await callback.answer("❌ Не удалось добавить", show_alert=True)

# 2. Обработка кнопки меню "⭐ Избранное"
@dp.message(F.text == "⭐ Избранное")
async def show_favorites_handler(message: types.Message):
    user_id = message.from_user.id
    logging.info(f"Пользователь {user_id} запросил список избранного")
    
    places = db.get_favorites(user_id)
    
    if not places:
        await message.answer("У тебя пока нет избранных мест. Самое время что-нибудь найти! 😊")
        return

    await message.answer(f"Твои избранные места ({len(places)}):")
    
    for place in places:
        metro_obj = place.get('metro_stations')
        metro_name = metro_obj.get('name') if metro_obj else "Не указано"
        text = (
            f"<b>{place['name']}</b>\n"
            f"🚇 {metro_name}\n"
            f"📍 {place['address']}"
        )
        
        # Кнопка для удаления из избранного (опционально) или просто ссылка
        if place.get('photo_url'):
            await message.answer_photo(photo=place['photo_url'], caption=text, parse_mode="HTML")
        else:
            await message.answer(text, parse_mode="HTML")

# Добавить новое заведение
# 1. Начало: спрашиваем Название
@dp.message(F.text == "➕ Добавить новое место")
async def add_place_start(message: types.Message, state: FSMContext):
    await state.set_state(AddPlace.waiting_for_name)
    await message.answer("Напиши название заведения:", reply_markup=ReplyKeyboardRemove())

# 2. Получили название, спрашиваем Тип
@dp.message(AddPlace.waiting_for_name)
async def add_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="Ресторан", callback_data="set_type_rest"))
    builder.add(types.InlineKeyboardButton(text="Кофейня", callback_data="set_type_cafe"))
    
    await state.set_state(AddPlace.waiting_for_type)
    await message.answer(f"Принято: {message.text}. Это ресторан или кофейня?", reply_markup=builder.as_markup())

# 3. Выбрали тип, предлагаем Метро (кнопками)
@dp.callback_query(AddPlace.waiting_for_type)
async def add_type(callback: types.CallbackQuery, state: FSMContext):
    res_type = "restaurant" if callback.data == "set_type_rest" else "cafe"
    await state.update_data(category=res_type)
    
    stations = db.get_all_metro()
    builder = InlineKeyboardBuilder()
    for s in stations:
        builder.add(types.InlineKeyboardButton(text=s['name'], callback_data=f"addmetro_{s['id']}"))
    
    builder.adjust(2)
    await state.set_state(AddPlace.waiting_for_metro)
    await callback.message.edit_text("Выбери ближайшее метро из списка:", reply_markup=builder.as_markup())
    await callback.answer()

# 4. Выбрали метро, спрашиваем АДРЕС (вот тут была ошибка)
@dp.callback_query(AddPlace.waiting_for_metro)
async def add_metro_callback(callback: types.CallbackQuery, state: FSMContext):
    # Находим название метро по ID для превью, либо просто сохраняем ID
    metro_id = int(callback.data.replace("addmetro_", ""))
    await state.update_data(metro_id=metro_id)
    
    # ПЕРЕХОДИМ К АДРЕСУ
    await state.set_state(AddPlace.waiting_for_address)
    await callback.message.answer("Введите точный адрес заведения:")
    await callback.answer()

# 5. Получили адрес, просим Фото
@dp.message(AddPlace.waiting_for_address)
async def add_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    await state.set_state(AddPlace.waiting_for_photo)
    await message.answer("Пришли фото заведения:")

# 6. Получили фото, выводим проверку данных
@dp.message(AddPlace.waiting_for_photo, F.photo)
async def add_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    
    data = await state.get_data()
    
    # Для превью можно достать имя метро из БД, если нужно
    preview = (
        f"<b>Проверь данные:</b>\n\n"
        f"📍 Название: {data['name']}\n"
        f"📁 Тип: {'Ресторан' if data['category'] == 'restaurant' else 'Кофейня'}\n"
        f"🏠 Адрес: {data['address']}"
    )
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="✅ Отправить админу", callback_data="confirm_send"))
    builder.add(types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add"))
    
    await state.set_state(AddPlace.waiting_for_confirm)
    await message.answer_photo(photo=photo_id, caption=preview, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "confirm_send")
async def send_to_admin(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    
    # 1. Достаем название метро по ID из БД, чтобы админу было понятно
    metro_id = data.get('metro_id')
    metro_name = "Не указано"
    
    if metro_id:
        # Делаем быстрый запрос к таблице метро
        res = db.supabase.table("metro_stations").select("name").eq("id", metro_id).single().execute()
        if res.data:
            metro_name = res.data['name']

    # 2. Формируем текст для админа
    admin_text = (
        f"🔔 <b>НОВАЯ ЗАЯВКА</b>\nОт: @{callback.from_user.username}\n\n"
        f"📍 Название: {data.get('name')}\n"
        f"📁 Тип: {'Ресторан' if data.get('category') == 'restaurant' else 'Кофейня'}\n"
        f"🚇 Метро: {metro_name}\n" # Теперь здесь название, а не ID
        f"🏠 Адрес: {data.get('address')}"
    )
    
    admin_kb = InlineKeyboardBuilder()
    admin_kb.add(types.InlineKeyboardButton(text="✅ Одобрить", callback_data="admin_approve"))
    admin_kb.add(types.InlineKeyboardButton(text="❌ Отклонить", callback_data="admin_decline"))
    
    # 3. Отправляем админу
    await bot.send_photo(
        chat_id=ADMIN_GROUP_ID, 
        photo=data['photo_id'], 
        caption=admin_text, 
        parse_mode="HTML", 
        reply_markup=admin_kb.as_markup()
    )
    
    # 4. Ответ пользователю
    await callback.message.edit_caption(caption="✅ Заявка отправлена модератору!", reply_markup=None)
    await callback.message.answer("Главное меню:", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "cancel_add")
async def cancel_add(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.", reply_markup=main_menu())
    await callback.answer()

# --- МОДЕРАЦИЯ (В ГРУППЕ) ---

@dp.callback_query(F.data == "admin_approve")
async def process_approve(callback: types.CallbackQuery):
    if str(callback.message.chat.id) != str(ADMIN_GROUP_ID):
        return
    
    text = callback.message.caption
    try:
        # 1. Извлекаем текстовые данные из сообщения админа с помощью регулярных выражений
        name = re.search(r"Название: (.+)", text).group(1).strip()
        cat_raw = re.search(r"Тип: (.+)", text).group(1).strip()
        category = "restaurant" if "Ресторан" in cat_raw else "cafe"
        metro_name = re.search(r"Метро: (.+)", text).group(1).strip()
        address = re.search(r"Адрес: (.+)", text).group(1).strip()
        photo_id = callback.message.photo[-1].file_id

        # 2. ВАЖНО: Находим ID станции метро по её названию
        # Это нужно, так как в таблицу places мы записываем metro_id (число)
        metro_res = db.supabase.table("metro_stations").select("id").eq("name", metro_name).single().execute()
        
        if not metro_res.data:
            await callback.answer(f"Ошибка: Станция '{metro_name}' не найдена в справочнике!", show_alert=True)
            return
            
        metro_id = metro_res.data['id']

        # 3. Сохраняем в базу (теперь передаем metro_id)
        db.insert_new_place(
            category=category, 
            name=name, 
            metro_id=metro_id, 
            address=address, 
            photo_url=photo_id  # В нашей логике это photo_id из Telegram
        )
        
        await callback.message.edit_caption(
            caption=text + f"\n\n✅ ОДОБРЕНО: @{callback.from_user.username}", 
            reply_markup=None
        )
        await callback.answer("Заведение успешно добавлено в базу!")
        
    except Exception as e:
        logging.error(f"Ошибка при одобрении: {e}")
        await callback.answer(f"Ошибка БД: {e}", show_alert=True)

@dp.callback_query(F.data == "admin_decline")
async def process_decline(callback: types.CallbackQuery):
    # Просто обновляем текст, помечая отказ
    await callback.message.edit_caption(
        caption=callback.message.caption + f"\n\n❌ ОТКЛОНЕНО: @{callback.from_user.username}", 
        reply_markup=None
    )
    await callback.answer("Заявка отклонена")

# Эхо-обработчик (ловит всё, что не попало в фильтры выше)
@dp.message()
async def unknown_msg(message: types.Message):
    await message.answer("Я тебя не понимаю. Используй кнопки меню или нажми /start")

# --- ЗАПУСК ---
async def main():
    # drop_pending_updates=True позволит боту не отвечать на старые сообщения при запуске
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот выключен пользователем")