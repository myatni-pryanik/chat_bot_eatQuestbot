import os
import asyncio
from dotenv import load_dotenv
from supabase import create_client, Client


# Загружаем переменные окружения из .env
load_dotenv()

# Инициализация клиента Supabase
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

if not url or not key:
    print("❌ ОШИБКА: SUPABASE_URL или SUPABASE_KEY не найдены в .env")


os.environ["HTTP_PROXY"] = "socks5://127.0.0.1:10808"
os.environ["HTTPS_PROXY"] = "socks5://127.0.0.1:10808"
supabase: Client = create_client(url, key)


async def register_user(user_id: int, username: str, full_name: str):
    """Регистрирует пользователя в базе, если его там еще нет"""
    data = {
        "user_id": user_id,
        "username": username,
        "first_name": full_name
    }
    
    # Запускаем синхронный .execute() в отдельном потоке, чтобы aiogram не ругался
    def run_sync():
        return supabase.table("users").upsert(data).execute()
        
    await asyncio.to_thread(run_sync)


def get_places(category: str, budget: str = None, metro_id: int = None, cuisine_id: int = None):
    """Получает список заведений по категории и фильтрам"""
    try:
        category = category.strip()
       
        query = (
            supabase.table("places")
            .select("*, metro_id(*), cuisine_id(*)")
            .ilike("category", f"%{category}%")
        )
        
        if budget:
            query = query.eq("budget_level", budget)
        if metro_id:
            query = query.eq("metro_id", metro_id)
        if cuisine_id:
            query = query.eq("cuisine_id", cuisine_id)
            
        response = query.execute()
        return response.data
    except Exception as e:
        print(f"❌ Ошибка при получении мест из Supabase: {e}")
        return []

    
# Функции для получения списков для кнопок в боте
def get_all_metro():
    return supabase.table("metro_stations").select("*").execute().data

def get_unique_lines():
    """Возвращает список всех уникальных веток метро из БД"""
    try:
        response = supabase.table("metro_stations").select("line").execute()
        # Собираем уникальные названия веток, исключая пустые (NULL), и сортируем
        lines = sorted(list(set(row['line'] for row in response.data if row.get('line'))))
        return lines
    except Exception as e:
        print(f"❌ Ошибка получения веток: {e}")
        return []

def get_metro_by_line(line_name: str):
    """Возвращает список станций, принадлежащих конкретной ветке"""
    try:
        response = supabase.table("metro_stations").select("id, name").eq("line", line_name).execute()
        return response.data
    except Exception as e:
        print(f"❌ Ошибка получения станций ветки: {e}")
        return []


def get_all_cuisines():
    return supabase.table("cuisines").select("*").execute().data

def add_to_favorites(user_id: int, place_id: int):
    """Добавляет заведение в избранное (или обновляет, если уже есть)"""
    try:
        data = {"user_id": user_id, "place_id": place_id}
        supabase.table("favorites").upsert(data).execute()
    except Exception as e:
        print(f"❌ Ошибка при добавлении в избранное: {e}")

def get_favorites(user_id: int):
    try:
        # Добавляем джойны: places(*, metro_stations(name), cuisines(name))
        response = supabase.table("favorites") \
            .select("places(*, metro_stations(name), cuisines(name))") \
            .eq("user_id", user_id) \
            .execute()
        
        places = [item['places'] for item in response.data if item.get('places')]
        return places
    except Exception as e:
        print(f"❌ Ошибка при получении избранного: {e}")
        return []

def insert_new_place(category, name, metro_id, address, photo_url):
    """Вставляет новое заведение (после одобрения админом)"""
    try:
        # В базе 'Ресторан' должен стать 'restaurant', а 'Кофейня' -> 'cafe'
        cat_map = {"Ресторан": "restaurant", "Кофейня": "cafe"}
        db_category = cat_map.get(category, category.lower())

        data = {
            "category": db_category,
            "name": name,
            "metro_id": metro_id,
            "address": address,
            "photo_url": photo_url,
            "is_active": True,
            "rating_cache": 0.0
        }
        supabase.table("places").insert(data).execute()
        print(f"✅ Заведение {name} успешно добавлено в базу.")
    except Exception as e:
        print(f"❌ Ошибка при вставке в базу: {e}")
        raise e