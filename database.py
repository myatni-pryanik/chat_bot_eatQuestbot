import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Загружаем переменные окружения из .env
load_dotenv()

# Инициализация клиента Supabase
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

if not url or not key:
    print("❌ ОШИБКА: SUPABASE_URL или SUPABASE_KEY не найдены в .env")

supabase: Client = create_client(url, key)

def register_user(user_id: int, username: str, full_name: str):
    """Регистрирует пользователя в базе, если его там еще нет"""
    data = {
        "user_id": user_id,
        "username": username,
        "first_name": full_name
    }
    # upsert обновит данные, если ID уже есть, или создаст новую строку
    supabase.table("users").upsert(data).execute()

def get_places(category: str, budget: int = None, metro_id: int = None, cuisine_id: int = None):
    """Получает список заведений по категории и фильтрам"""
    try:
        # Базовый запрос: выбираем активные заведения нужной категории
        query = supabase.table("places").select("*, metro_stations(name), cuisines(name)").eq("category", category).eq("is_active", True)
        
        # Добавляем фильтры, если они переданы
        if budget:
            query = query.eq("budget_level", budget)
        if metro_id:
            query = query.eq("metro_id", metro_id)
        if cuisine_id:
            query = query.eq("cuisine_id", cuisine_id)
            
        response = query.execute()
        return response.data
    except Exception as e:
        print(f"❌ Ошибка при получении мест: {e}")
        return []
    
# Функции для получения списков для кнопок в боте
def get_all_metro():
    return supabase.table("metro_stations").select("*").execute().data

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
        # Убираем лишний cat_map, если из бота уже летит 'restaurant'
        data = {
            "category": category,
            "name": name,
            "metro_id": metro_id,
            "address": address,
            "photo_url": photo_url,
            "is_active": True,
            "rating_cache": 0.0
        }
        supabase.table("places").insert(data).execute()
        print(f"✅ Заведение {name} добавлено.")
    except Exception as e:
        print(f"❌ Ошибка при вставке: {e}")
        raise e