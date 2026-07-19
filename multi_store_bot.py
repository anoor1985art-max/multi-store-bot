import os
import sys
import json
import uuid
import time
import copy
import threading
import random
from dotenv import load_dotenv
import telebot
from telebot import types

log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "multi_store_bot.log")
class SafeStream:
    def __init__(self, original_stream):
        self.original_stream = original_stream
        self.log_file = open(log_path, "a", encoding="utf-8")
    def write(self, data):
        try:
            if self.original_stream:
                self.original_stream.write(data)
                self.original_stream.flush()
        except Exception:
            pass
        try:
            self.log_file.write(data)
            self.log_file.flush()
        except Exception:
            pass
    def flush(self):
        try:
            if self.original_stream: self.original_stream.flush()
            self.log_file.flush()
        except Exception:
            pass

sys.stdout = SafeStream(sys.stdout)
sys.stderr = SafeStream(sys.stderr)

load_dotenv()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SUPER_ADMIN_ID = str(os.environ.get("SUPER_ADMIN_ID", "")).strip()

if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("[WARNING] يرجى وضع توكن البوت في ملف .env داخل المتغير TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML") if TOKEN and TOKEN != "YOUR_BOT_TOKEN_HERE" else None

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.json")
db_lock = threading.Lock()

from store_db_handler import load_db as sqlite_load_db, save_db as sqlite_save_db

def load_db():
    with db_lock:
        return sqlite_load_db()

def register_user(chat_id):
    try:
        db = load_db()
        if "users" not in db:
            db["users"] = []
        if chat_id not in db["users"]:
            db["users"].append(chat_id)
            save_db(db)
    except Exception:
        pass

def save_db(data):
    with db_lock:
        sqlite_save_db(data)

def format_price(amount):
    try:
        if isinstance(amount, (int, float)):
            if amount == int(amount):
                return f"{int(amount):,} د.ع"
            else:
                return f"{amount:,.2f} د.ع"
        return f"{amount} د.ع"
    except Exception:
        return f"{amount} د.ع"

def get_store_ui_terms(store):
    sec = store.get("sector", "")
    if sec in ["food", "cafe"]:
        return {
            "item_name": "الطبق/الصنف",
            "item_single": "طبق",
            "item_plural": "أطباق/أصناف",
            "store_lbl": "المطعم/الكافيه",
            "sections_lbl": "أقسام المطعم/الكافيه",
            "not_in_cart": "🛒 الصنف غير مضاف للسلة بعد",
            "empty_sec": "❌ لا توجد أطباق أو أصناف حالياً داخل هذا القسم، يرجى تصفحه لاحقاً."
        }
    elif sec == "shopping":
        return {
            "item_name": "المنتج/السلعة",
            "item_single": "منتج",
            "item_plural": "منتجات/سلع",
            "store_lbl": "المتجر",
            "sections_lbl": "أقسام المتجر",
            "not_in_cart": "🛒 المنتج غير مضاف للسلة بعد",
            "empty_sec": "❌ لا توجد منتجات أو سلع حالياً داخل هذا القسم، يرجى تصفحه لاحقاً."
        }
    else:
        return {
            "item_name": "المنتج/الصنف",
            "item_single": "منتج",
            "item_plural": "منتجات/أصناف",
            "store_lbl": "المتجر",
            "sections_lbl": "أقسام المتجر",
            "not_in_cart": "🛒 المنتج غير مضاف للسلة بعد",
            "empty_sec": "❌ لا توجد منتجات أو أصناف حالياً داخل هذا القسم، يرجى تصفحه لاحقاً."
        }

# هيكل ذاكرة التخزين المؤقت:
# user_states: { chat_id: {"state": "...", "store_id": "...", "data": {...}} }
# user_carts: { chat_id: { store_id: { prod_id: quantity } } }
user_states = {}
user_carts = {}
user_order_types = {}  # { chat_id: { store_id: "🍽️ صالة (طاولة رقم 5)" } }

def get_user_order_type(chat_id, store_id):
    if chat_id not in user_order_types:
        user_order_types[chat_id] = {}
    return user_order_types[chat_id].get(store_id)

def set_user_order_type(chat_id, store_id, order_type):
    if chat_id not in user_order_types:
        user_order_types[chat_id] = {}
    user_order_types[chat_id][store_id] = order_type

def get_user_state(chat_id):
    return user_states.get(chat_id, {}).get("state", "menu")

def set_user_state(chat_id, state, store_id=None, extra_data=None):
    if chat_id not in user_states:
        user_states[chat_id] = {}
    user_states[chat_id]["state"] = state
    if store_id:
        user_states[chat_id]["store_id"] = store_id
    if extra_data is not None:
        user_states[chat_id]["data"] = extra_data

def clear_user_state(chat_id):
    if chat_id in user_states:
        user_states[chat_id] = {"state": "menu"}

def is_super_admin(chat_id):
    load_dotenv(override=True)
    current_admin = str(os.environ.get("SUPER_ADMIN_ID", "")).strip()
    return str(chat_id) == current_admin

def is_store_admin(chat_id, store_id):
    if is_super_admin(chat_id):
        return True
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    return str(store.get("admin_id", "")).strip() == str(chat_id)

def get_user_cart(chat_id, store_id):
    if chat_id not in user_carts:
        user_carts[chat_id] = {}
    if store_id not in user_carts[chat_id]:
        user_carts[chat_id][store_id] = {}
    return user_carts[chat_id][store_id]

def add_to_cart(chat_id, store_id, prod_id, qty=1):
    cart = get_user_cart(chat_id, store_id)
    cart[prod_id] = cart.get(prod_id, 0) + qty
    if cart[prod_id] <= 0:
        del cart[prod_id]

# ==========================================
# 1. واجهة المجمع التجاري (Mall Main Menu) والأجنحة
# ==========================================
def send_mall_menu(chat_id, message_id=None):
    db = load_db()
    stores = db.get("stores", {})
    
    # حساب عدد المتاجر الظاهرة في كل جناح
    counts = {"food": 0, "cafe": 0, "shopping": 0}
    for s_id, s_info in stores.items():
        if not s_info.get("hidden", False) or is_store_admin(chat_id, s_id):
            sec = s_info.get("sector")
            if not sec:
                if s_id == "food_store":
                    sec = "food"
                elif s_id == "cafe_store":
                    sec = "cafe"
                else:
                    sec = "shopping"
            if sec in counts:
                counts[sec] += 1
            else:
                counts["shopping"] += 1

    is_admin_any = is_super_admin(chat_id)
    if not is_admin_any:
        for s_info in stores.values():
            if str(s_info.get("admin_id", "")).strip() == str(chat_id):
                is_admin_any = True
                break

    markup = types.InlineKeyboardMarkup(row_width=1)
    if counts["food"] > 0 or is_admin_any:
        markup.add(types.InlineKeyboardButton(f"🍔 جناح المطاعم والوجبات السريعة ({counts['food']} مطعم)", callback_data="open_sector|food"))
    if counts["cafe"] > 0 or is_admin_any:
        markup.add(types.InlineKeyboardButton(f"☕ جناح الكافيهات والمشروبات والحلويات ({counts['cafe']} متجر)", callback_data="open_sector|cafe"))
    if counts["shopping"] > 0 or is_admin_any:
        markup.add(types.InlineKeyboardButton(f"🛍️ جناح المتاجر والسلع والتسوق ({counts['shopping']} متجر)", callback_data="open_sector|shopping"))

    if sum(counts.values()) > 0 or is_admin_any:
        markup.add(types.InlineKeyboardButton("🏬 تصفح كافة متاجر المجمع في قائمة واحدة", callback_data="open_all_stores"))
    markup.add(types.InlineKeyboardButton("📜 سجل طلباتي السابقة", callback_data="my_orders"))

    if is_admin_any:
        markup.add(
            types.InlineKeyboardButton("👑 لوحة تحكم الإدارة والمتاجر", callback_data="admin_main"),
            types.InlineKeyboardButton("👁️ محاكاة شاشة الزبون (بدون المخفي)", callback_data="preview_customer")
        )
    
    text = (
        "🏢 <b>أهلاً بك في المجمع التجاري الذكي متعدد المتاجر! 🛍️✨</b>\n\n"
        "إليك أجنحة المجمع المتاحة اليوم، اضغط على الجناح المناسب لتصفح المتاجر والمطاعم المستقلة داخله:"
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_my_orders(chat_id, message_id=None):
    db = load_db()
    orders = db.get("orders", {})
    user_orders = []
    for oid, o_data in orders.items():
        if str(o_data.get("chat_id")) == str(chat_id):
            user_orders.append(o_data)
    
    user_orders.sort(key=lambda x: x.get("time", ""), reverse=True)
    recent_orders = user_orders[:10]
    
    status_map = {
        "pending": "⏳ قيد المراجعة",
        "accepted": "✅ مقبول وقيد التجهيز",
        "delivered": "🚗 خرج للتوصيل / جاهز",
        "rejected": "❌ مرفوض / ملغي",
        "completed": "🏁 مكتمل"
    }
    
    if not recent_orders:
        text = "📜 <b>سجل طلباتك السابقة فارغ حالياً.</b>\n\nلم تقم بأي طلب من متاجر المجمع بعد، تصفح الأجنحة وابدأ التسوق الآن!"
    else:
        text = "📜 <b>سجل آخر طلباتك في المجمع التجاري:</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        for o in recent_orders:
            s_name = db.get("stores", {}).get(o.get("store_id"), {}).get("name", "متجر")
            st_text = status_map.get(o.get("status", "pending"), o.get("status", "pending"))
            text += (
                f"🔖 <b>رقم الطلب:</b> <code>#{o.get('id', '')}</code>\n"
                f"🏬 <b>المتجر:</b> {s_name}\n"
                f"🍽️ <b>النوع:</b> {o.get('order_type', 'سفري')}\n"
                f"💰 <b>الإجمالي:</b> <code>{format_price(o.get('total', 0))}</code>\n"
                f"🏷️ <b>الحالة:</b> {st_text}\n"
                f"📅 <i>{o.get('time', '')}</i>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
            )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 العودة للمول الرئيسي", callback_data="mall_home"))
    
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_sector_stores(chat_id, sector_key, message_id=None):
    db = load_db()
    stores = db.get("stores", {})
    sec_titles = {
        "food": "🍔 جناح المطاعم والوجبات السريعة",
        "cafe": "☕ جناح الكافيهات والمشروبات والحلويات",
        "shopping": "🛍️ جناح المتاجر والسلع والتسوق"
    }
    title = sec_titles.get(sector_key, "🏬 متاجر المجمع")

    markup = types.InlineKeyboardMarkup(row_width=1)
    found = 0
    for s_id, s_info in stores.items():
        sec = s_info.get("sector")
        if not sec:
            if s_id == "food_store":
                sec = "food"
            elif s_id == "cafe_store":
                sec = "cafe"
            else:
                sec = "shopping"
        if sec == sector_key:
            if not s_info.get("hidden", False) or is_store_admin(chat_id, s_id):
                found += 1
                status_badge = " 🔒 [مخفي عن الزبائن]" if s_info.get("hidden", False) else ""
                markup.add(types.InlineKeyboardButton(f"🏬 {s_info.get('name', 'متجر')}{status_badge}", callback_data=f"open_store|{s_id}"))

    markup.add(types.InlineKeyboardButton("🔙 العودة لقائمة أجنحة المول", callback_data="mall_home"))

    if found == 0:
        text = f"🏢 <b>{title}</b>\n━━━━━━━━━━━━━━━━━━\n\nلا توجد متاجر متاحة في هذا الجناح حالياً."
    else:
        text = f"🏢 <b>{title}</b>\n━━━━━━━━━━━━━━━━━━\n\nإليك قائمة بالمتاجر والمطاعم المستقلة المتاحة في هذا الجناح، اختر المتجر المفضل:"

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_all_stores(chat_id, message_id=None):
    db = load_db()
    stores = db.get("stores", {})
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s_id, s_info in stores.items():
        if not s_info.get("hidden", False) or is_store_admin(chat_id, s_id):
            status_badge = " 🔒 [مخفي]" if s_info.get("hidden", False) else ""
            markup.add(types.InlineKeyboardButton(f"🏬 {s_info.get('name', 'متجر')}{status_badge}", callback_data=f"open_store|{s_id}"))
    markup.add(types.InlineKeyboardButton("🔙 العودة لقائمة أجنحة المول", callback_data="mall_home"))

    text = "🏬 <b>قائمة جميع متاجر ومطاعم المجمع:</b>\nاختر المتجر الذي ترغب بزيارته:"
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

# ==========================================
# 2. واجهة المتجر وقائمة الأقسام والمنتجات
# ==========================================
def send_store_home(chat_id, store_id, message_id=None):
    db = load_db()
    store = db.get("stores", {}).get(store_id)
    if not store:
        bot.send_message(chat_id, "❌ عذراً، هذا المتجر لم يعد متاحاً.")
        send_mall_menu(chat_id)
        return

    if store.get("hidden", False) and not is_store_admin(chat_id, store_id):
        bot.send_message(chat_id, "🔒 عذراً، هذا المتجر مغلق مؤقتاً أو مخفي من قبل الإدارة حالياً.")
        send_mall_menu(chat_id)
        return

    cart = get_user_cart(chat_id, store_id)
    total_items = sum(cart.values())

    markup = types.InlineKeyboardMarkup(row_width=2)
    for cat_id, cat_name in store.get("categories", {}).items():
        markup.add(types.InlineKeyboardButton(f"📁 {cat_name}", callback_data=f"open_cat|{store_id}|{cat_id}"))
    
    sec = store.get("sector")
    if not sec:
        if store_id == "food_store": sec = "food"
        elif store_id == "cafe_store": sec = "cafe"
        else: sec = "shopping"

    if sec in ["food", "cafe"]:
        current_type = get_user_order_type(chat_id, store_id)
        status_lbl = current_type if current_type else "لم يحدد (سفري أم صالة؟)"
        markup.add(types.InlineKeyboardButton(f"🏷️ نوع الطلب: {status_lbl}", callback_data="ignore_cb"))
        markup.add(
            types.InlineKeyboardButton("🛍️ طلب سفري", callback_data=f"set_takeaway|{store_id}"),
            types.InlineKeyboardButton("🍽️ طلب صالة (طاولات)", callback_data=f"choose_table|{store_id}")
        )

    markup.add(
        types.InlineKeyboardButton(f"🛒 سلة مشترياتي ({total_items})", callback_data=f"view_cart|{store_id}"),
        types.InlineKeyboardButton("🔙 العودة لقائمة المتاجر", callback_data="mall_home")
    )

    if is_store_admin(chat_id, store_id):
        hide_txt = "🟢 إظهار المتجر" if store.get("hidden", False) else "👁️ إخفاء المتجر"
        markup.add(types.InlineKeyboardButton("⚙️ إدارة وتعديل هذا المتجر", callback_data=f"admin_store|{store_id}"))
        markup.add(
            types.InlineKeyboardButton("✏️ تغيير اسم المتجر", callback_data=f"aset_name|{store_id}"),
            types.InlineKeyboardButton(hide_txt, callback_data=f"toggle_hide|{store_id}")
        )

    text = (
        f"🏬 <b>{store['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💬 <i>{store['desc']}</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 <b>اختر القسم الذي ترغب بتصفحه من الأزرار أدناه:</b>"
    )

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_pos_card(chat_id, store_id, cat_id, idx=0, message_id=None, only_caption=False):
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    terms = get_store_ui_terms(store)
    cat_name = store.get("categories", {}).get(cat_id, "قسم غير معروف")
    
    products = [p for p in store.get("products", {}).values() if p.get("category_id") == cat_id]
    
    if not products:
        if message_id:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
        text = f"📁 <b>{cat_name}</b>\n\n{terms['empty_sec']}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 العودة لأقسام المتجر", callback_data=f"open_store|{store_id}"))
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    total_prods = len(products)
    idx = idx % total_prods  # تنقل دائري سلس
    prod = products[idx]
    prod_id = prod['id']

    cart = get_user_cart(chat_id, store_id)
    qty = cart.get(prod_id, 0)
    item_total = qty * prod['price']

    desc_text = f"<i>{prod['desc']}</i>" if prod.get('desc') else "<i>لا توجد تفاصيل أو مكونات إضافية</i>"

    old_p = prod.get("old_price", 0)
    price_str = f"<s>{format_price(old_p)}</s> ➔ <b>{format_price(prod['price'])}</b> <i>(توفير مميز! 🔥)</i>" if old_p > prod['price'] else f"<code>{format_price(prod['price'])}</code>"

    caption = (
        f"📁 <b>القسم:</b> {cat_name}  |  <b>[ {terms['item_single']} {idx + 1} من {total_prods} ]</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ <b>{prod['name']}</b>\n"
        f"💰 <b>السعر:</b> {price_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>الوصف والتفاصيل:</b>\n{desc_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    if qty > 0:
        caption += f"🛒 <b>الكمية في سلتك:</b> ({qty}) | <b>الإجمالي:</b> <code>{format_price(item_total)}</code>"
    else:
        caption += f"🛒 <i>{terms['not_in_cart']}</i>"

    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # الصف الأول: أزرار (+) و (-) لكمية هذا المنتج مباشرة
    markup.add(
        types.InlineKeyboardButton("➖", callback_data=f"pos_dec|{store_id}|{cat_id}|{idx}|{prod_id}"),
        types.InlineKeyboardButton("➕ إضافة", callback_data=f"pos_inc|{store_id}|{cat_id}|{idx}|{prod_id}")
    )
    
    # الصف الثاني: أزرار التنقل بين منتجات القسم (السابق والتالي)
    if total_prods > 1:
        prev_idx = (idx - 1) % total_prods
        next_idx = (idx + 1) % total_prods
        markup.add(
            types.InlineKeyboardButton("◀️ السابق", callback_data=f"pos_nav|{store_id}|{cat_id}|{prev_idx}"),
            types.InlineKeyboardButton(f"📋 {idx + 1} / {total_prods}", callback_data="ignore_cb"),
            types.InlineKeyboardButton("التالي ▶️", callback_data=f"pos_nav|{store_id}|{cat_id}|{next_idx}")
        )
    
    # الصف الثالث: إتمام الطلب سريعاً وزر العودة
    total_items = sum(cart.values())
    total_price = sum(store.get("products", {}).get(pid, {}).get("price", 0) * q for pid, q in cart.items() if pid in store.get("products", {}))
    
    if total_items > 0:
        markup.add(types.InlineKeyboardButton(f"🛒 إتمام الطلب ({total_items} {terms['item_plural']} - {format_price(total_price)})", callback_data=f"view_cart|{store_id}"))

    markup.add(types.InlineKeyboardButton("🔙 العودة لأقسام المتجر", callback_data=f"open_store|{store_id}"))

    img_url = prod.get("image", "").strip()

    # تحديث الكابتشن فقط إذا كان نفس المنتج (عند الضغط على + أو -)
    if only_caption and message_id:
        if img_url:
            try:
                bot.edit_message_caption(caption, chat_id=chat_id, message_id=message_id, reply_markup=markup)
                return
            except Exception:
                pass
        else:
            try:
                bot.edit_message_text(caption, chat_id=chat_id, message_id=message_id, reply_markup=markup)
                return
            except Exception:
                pass

    # عند التنقل (التالي/السابق) أو عند العرض لأول مرة
    if img_url:
        if message_id:
            try:
                bot.edit_message_media(
                    media=types.InputMediaPhoto(media=img_url, caption=caption),
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=markup
                )
                return
            except Exception:
                try:
                    bot.delete_message(chat_id, message_id)
                except Exception:
                    pass
        try:
            bot.send_photo(chat_id, img_url, caption=caption, reply_markup=markup)
            return
        except Exception as e:
            print(f"[Send photo error]: {e}")

    if message_id:
        try:
            bot.edit_message_text(caption, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
    bot.send_message(chat_id, caption, reply_markup=markup)

def send_category_products(chat_id, store_id, cat_id, message_id=None):
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    terms = get_store_ui_terms(store)
    cat_name = store.get("categories", {}).get(cat_id, "قسم غير معروف")
    
    products = [p for p in store.get("products", {}).values() if p.get("category_id") == cat_id]
    
    cart = get_user_cart(chat_id, store_id)
    total_cart_items = sum(cart.values())
    total_cart_price = sum(store.get("products", {}).get(pid, {}).get("price", 0) * q for pid, q in cart.items() if pid in store.get("products", {}))

    if message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

    if not products:
        text = f"📁 <b>قسم: {cat_name}</b>\n\n{terms['empty_sec']}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 العودة لأقسام المتجر", callback_data=f"open_store|{store_id}"))
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    # إرسال ترويسة القسم مع أزرار السلة والعودة للأقسام
    header_text = (
        f"📁 <b>قسم: {cat_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👇 <i>قائمة ال{terms['item_plural']} بنظام التصفح المباشر (تعديل الكمية فوراً من الأزرار أسفل كل صورة):</i>\n"
    )
    header_markup = types.InlineKeyboardMarkup(row_width=2)
    header_markup.add(
        types.InlineKeyboardButton(f"🛒 سلتك الآن ({total_cart_items}) - [{format_price(total_cart_price)}]", callback_data=f"view_cart|{store_id}"),
        types.InlineKeyboardButton("🔙 العودة للأقسام", callback_data=f"open_store|{store_id}")
    )
    bot.send_message(chat_id, header_text, reply_markup=header_markup)

    # إرسال كل منتج كبطاقة مصورة مستقلة
    for p in products:
        send_product_card(chat_id, store_id, p['id'], message_id=None)

def send_product_card(chat_id, store_id, prod_id, message_id=None):
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    terms = get_store_ui_terms(store)
    prod = store.get("products", {}).get(prod_id)
    if not prod:
        if not message_id:
            bot.send_message(chat_id, f"❌ {terms['item_name']} لم يعد متوفراً.")
        return

    cart = get_user_cart(chat_id, store_id)
    qty = cart.get(prod_id, 0)
    item_total = qty * prod['price']

    desc_text = f"<i>{prod['desc']}</i>" if prod.get('desc') else "<i>لا توجد تفاصيل إضافية</i>"

    old_p = prod.get("old_price", 0)
    price_str = f"<s>{format_price(old_p)}</s> ➔ <b>{format_price(prod['price'])}</b> <i>(توفير مميز! 🔥)</i>" if old_p > prod['price'] else f"<code>{format_price(prod['price'])}</code>"

    caption = (
        f"🏷️ <b>{prod['name']}</b>\n"
        f"💰 <b>السعر:</b> {price_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>الوصف والمكونات:</b>\n{desc_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    if qty > 0:
        caption += f"🛒 <b>الكمية في سلتك:</b> ({qty})  |  <b>الإجمالي:</b> <code>{format_price(item_total)}</code>"
    else:
        caption += f"🛒 <i>{terms['not_in_cart']} (اضغط + للإضافة)</i>"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➖", callback_data=f"dec_cart|{store_id}|{prod_id}"),
        types.InlineKeyboardButton("➕ إضافة", callback_data=f"inc_cart|{store_id}|{prod_id}")
    )
    
    total_items = sum(cart.values())
    total_price = sum(store.get("products", {}).get(pid, {}).get("price", 0) * q for pid, q in cart.items() if pid in store.get("products", {}))
    
    if total_items > 0:
        markup.add(types.InlineKeyboardButton(f"🛒 إتمام الطلب ({total_items} {terms['item_plural']} - {format_price(total_price)})", callback_data=f"view_cart|{store_id}"))

    img_url = prod.get("image", "").strip()
    if img_url:
        if message_id:
            try:
                bot.edit_message_caption(caption, chat_id=chat_id, message_id=message_id, reply_markup=markup)
                return
            except Exception:
                try:
                    bot.delete_message(chat_id, message_id)
                except Exception:
                    pass
        try:
            bot.send_photo(chat_id, img_url, caption=caption, reply_markup=markup)
            return
        except Exception as e:
            print(f"[Send photo error]: {e}")

    if message_id:
        try:
            bot.edit_message_text(caption, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, caption, reply_markup=markup)


# ==========================================
# 3. سلة المشتريات وإتمام الطلب (Cart & Checkout)
# ==========================================
def send_cart_view(chat_id, store_id, message_id=None):
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    cart = get_user_cart(chat_id, store_id)

    if not cart:
        text = f"🛒 <b>سلة مشترياتك في «{store.get('name', 'المتجر')}» فارغة تماماً.</b>\n\nتصفح أقسامنا وأضف ما يعجبك الآن!"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 العودة للتسوق", callback_data=f"open_store|{store_id}"))
    else:
        text = f"🛒 <b>سلة مشترياتك في:</b> {store.get('name', 'المتجر')}\n━━━━━━━━━━━━━━━━━━\n"
        total = 0.0
        markup = types.InlineKeyboardMarkup(row_width=3)
        for p_id, qty in cart.items():
            prod = store.get("products", {}).get(p_id)
            if prod:
                subtotal = prod["price"] * qty
                total += subtotal
                text += f"🔹 <b>{prod['name']}</b>\n     الكمية: {qty} × {format_price(prod['price'])} = <code>{format_price(subtotal)}</code>\n"
                markup.add(
                    types.InlineKeyboardButton("➖", callback_data=f"dec_cart|{store_id}|{p_id}"),
                    types.InlineKeyboardButton(f"{prod['name'][:15]} ({qty})", callback_data=f"view_prod|{store_id}|{p_id}"),
                    types.InlineKeyboardButton("➕", callback_data=f"inc_cart|{store_id}|{p_id}")
                )
        text += f"━━━━━━━━━━━━━━━━━━\n💰 <b>المبلغ الإجمالي المطلُوب: <code>{format_price(total)}</code></b>\n\n👇 اضغط على زر إتمام الطلب لتعبئة بيانات التوصيل والدفع:"
        markup.add(types.InlineKeyboardButton("✅ إتمام الطلب وتعبئة البيانات 🚀", callback_data=f"checkout|{store_id}"))
        markup.add(
            types.InlineKeyboardButton("🗑️ تفريغ السلة", callback_data=f"clear_cart|{store_id}"),
            types.InlineKeyboardButton("🔙 العودة للتسوق", callback_data=f"open_store|{store_id}")
        )

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_order_type_selection(chat_id, store_id, message_id=None, is_checkout=False):
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    prefix = "set_takeaway_chk" if is_checkout else "set_takeaway"
    tbl_prefix = "choose_table_chk" if is_checkout else "choose_table"
    back_cb = f"view_cart|{store_id}" if is_checkout else f"open_store|{store_id}"

    sector = store.get("sector")
    if not sector:
        if store_id == "food_store":
            sector = "food"
        elif store_id == "cafe_store":
            sector = "cafe"
        else:
            sector = "shopping"

    delivery_mode = store.get("delivery_mode", "none" if sector == "cafe" else "paid" if store.get("delivery_fee", 0) > 0 else "free")

    markup = types.InlineKeyboardMarkup(row_width=2)
    if sector == "cafe" or delivery_mode == "none":
        text = (
            f"🍽️ <b>تحديد طريقة استلام الطلب من «{store.get('name', 'الكافيه/المتجر')}»</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ <b>تنبيه:</b> خدمة التوصيل الخارجي غير متوفرة لهذا المتجر.\n"
            f"يرجى الاختيار بين الاستلام المباشر من البار/الفرع أو الجلوس في الصالة:"
        )
        markup.add(
            types.InlineKeyboardButton("🚶 استلام من الفرع / البار (Pickup)", callback_data=f"{prefix}|{store_id}"),
            types.InlineKeyboardButton("🍽️ طلب داخل الصالة (Dine-in)", callback_data=f"{tbl_prefix}|{store_id}")
        )
    else:
        text = (
            f"🍽️ <b>تحديد طريقة استلام الطلب من «{store.get('name', 'المطعم/المتجر')}»</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"يرجى اختيار العودة لطاولة داخل (صالة المطعم) أم طلب سفري أو توصيل خارجي:"
        )
        markup.add(
            types.InlineKeyboardButton("🛍️ طلب سفري (Takeaway / توصيل)", callback_data=f"{prefix}|{store_id}"),
            types.InlineKeyboardButton("🍽️ طلب داخل الصالة (Dine-in)", callback_data=f"{tbl_prefix}|{store_id}")
        )
    markup.add(types.InlineKeyboardButton("🔙 العودة للخلف", callback_data=back_cb))

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_table_selection(chat_id, store_id, message_id=None, is_checkout=False):
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    prefix = "sel_table_chk" if is_checkout else "sel_table"

    text = (
        f"🍽️ <b>اختيار رقم الطاولة — {store.get('name', 'المطعم')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"يرجى الضغط على رقم الطاولة التي تجلس عليها داخل الصالة ليقوم النديل بتقديم طلبك إليها مباشرة:"
    )
    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(1, 16):
        buttons.append(types.InlineKeyboardButton(f" طاولة {i} ", callback_data=f"{prefix}|{store_id}|{i}"))
    for i in range(0, len(buttons), 5):
        markup.add(*buttons[i:i+5])

    back_cb = f"choose_type_chk|{store_id}" if is_checkout else f"open_store|{store_id}"
    markup.add(types.InlineKeyboardButton("🔙 العودة للخلف", callback_data=back_cb))

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def start_checkout_flow(chat_id, store_id, message_id=None):
    order_type = get_user_order_type(chat_id, store_id)
    if order_type and "صالة" in order_type:
        extra_data = {
            "order_type": order_type,
            "customer_name": f"زبون في {order_type}",
            "customer_phone": "طلب صالة داخلي"
        }
        send_payment_selection(chat_id, store_id, extra_data, address_text=order_type)
        return

    extra_data = {}
    if order_type:
        extra_data["order_type"] = order_type
    set_user_state(chat_id, "checkout_name", store_id, extra_data)

    type_header = f" (<b>{order_type}</b>)\n" if order_type else " (🛍️ سفري/توصيل)\n"
    text = (
        f"📝 <b>خطوات إتمام الطلب{type_header}</b>"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "👤 <b>[1/3]</b> يرجى إرسال <b>اسمك الكامل</b> الآن في رسالة لنعتمده في الفاتورة والتوصيل:"
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text)

# ==========================================
# محاكاة شاشة الزبون العادي للإدمن (Customer Preview)
# ==========================================
def send_customer_preview(chat_id, message_id=None):
    db = load_db()
    stores = db.get("stores", {})
    
    counts = {"food": 0, "cafe": 0, "shopping": 0}
    for s_id, s_info in stores.items():
        if not s_info.get("hidden", False):
            sec = s_info.get("sector")
            if not sec:
                if s_id == "food_store": sec = "food"
                elif s_id == "cafe_store": sec = "cafe"
                else: sec = "shopping"
            if sec in counts: counts[sec] += 1
            else: counts["shopping"] += 1

    markup = types.InlineKeyboardMarkup(row_width=1)
    if counts["food"] > 0:
        markup.add(types.InlineKeyboardButton(f"🍔 جناح المطاعم والوجبات السريعة ({counts['food']} مطعم)", callback_data="prev_sec|food"))
    if counts["cafe"] > 0:
        markup.add(types.InlineKeyboardButton(f"☕ جناح الكافيهات والمشروبات والحلويات ({counts['cafe']} متجر)", callback_data="prev_sec|cafe"))
    if counts["shopping"] > 0:
        markup.add(types.InlineKeyboardButton(f"🛍️ جناح المتاجر والسلع والتسوق ({counts['shopping']} متجر)", callback_data="prev_sec|shopping"))

    if sum(counts.values()) > 0:
        markup.add(types.InlineKeyboardButton("🏬 تصفح كافة متاجر المجمع للزبائن", callback_data="prev_all"))
    markup.add(types.InlineKeyboardButton("🛑 خروج من وضع المحاكاة والعودة للإدارة", callback_data="admin_main"))

    if sum(counts.values()) == 0:
        text = (
            "👁️ <b>[وضع محاكاة شاشة الزبون العادي]</b>\n\n"
            "🔒 <b>جميع أجنحة ومتاجر المجمع مخفية حالياً!</b>\n\n"
            "الزبون العادي عند دخوله للمول الآن لن يرى أي أجنحة أو متاجر نهائياً، بل ستظهر له رسالة بأن المجمع قيد التحديث والصيانة."
        )
    else:
        text = (
            "👁️ <b>[وضع محاكاة شاشة الزبون العادي]</b>\n\n"
            "هكذا يرى الزبائن العاديون أجنحة ومتاجر المجمع الآن <b>(الأجنحة الفارغة التي لا تحتوي متاجر ظاهرة لا تظهر على شاشة الزبون نهائياً)</b>:\n\n"
            "👇 يمكنك تصفح الأجنحة المتاحة للزبون أدناه:"
        )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_customer_preview_sector(chat_id, sector_key, message_id=None):
    db = load_db()
    stores = db.get("stores", {})
    sec_titles = {
        "food": "🍔 جناح المطاعم والوجبات السريعة (شاشة الزبون)",
        "cafe": "☕ جناح الكافيهات والمشروبات والحلويات (شاشة الزبون)",
        "shopping": "🛍️ جناح المتاجر والسلع والتسوق (شاشة الزبون)"
    }
    title = sec_titles.get(sector_key, "🏬 متاجر المجمع")

    markup = types.InlineKeyboardMarkup(row_width=1)
    found = 0
    for s_id, s_info in stores.items():
        sec = s_info.get("sector")
        if not sec:
            if s_id == "food_store": sec = "food"
            elif s_id == "cafe_store": sec = "cafe"
            else: sec = "shopping"
        if sec == sector_key and not s_info.get("hidden", False):
            found += 1
            markup.add(types.InlineKeyboardButton(f"🏬 {s_info.get('name', 'متجر')}", callback_data=f"open_store|{s_id}"))

    markup.add(
        types.InlineKeyboardButton("🔙 العودة لأجنحة محاكاة الزبون", callback_data="preview_customer"),
        types.InlineKeyboardButton("🛑 خروج للوحة الإدارة", callback_data="admin_main")
    )

    if found == 0:
        text = f"👁️ <b>{title}</b>\n━━━━━━━━━━━━━━━━━━\n\nلا توجد متاجر متاحة للزبائن في هذا الجناح حالياً (جميعها مخفية أو قيد الإنشاء)."
    else:
        text = f"👁️ <b>{title}</b>\n━━━━━━━━━━━━━━━━━━\n\nإليك المتاجر المتاحة والظاهرة للزبائن في هذا الجناح:"

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_customer_preview_all(chat_id, message_id=None):
    db = load_db()
    stores = db.get("stores", {})
    markup = types.InlineKeyboardMarkup(row_width=1)
    found = 0
    for s_id, s_info in stores.items():
        if not s_info.get("hidden", False):
            found += 1
            markup.add(types.InlineKeyboardButton(f"🏬 {s_info.get('name', 'متجر')}", callback_data=f"open_store|{s_id}"))
    markup.add(
        types.InlineKeyboardButton("🔙 العودة لأجنحة محاكاة الزبون", callback_data="preview_customer"),
        types.InlineKeyboardButton("🛑 خروج للوحة الإدارة", callback_data="admin_main")
    )

    if found == 0:
        text = "👁️ <b>قائمة جميع المتاجر (شاشة الزبون)</b>\n━━━━━━━━━━━━━━━━━━\n\nلا توجد أي متاجر متاحة للزبائن حالياً."
    else:
        text = "👁️ <b>قائمة جميع المتاجر (شاشة الزبون):</b>\nهذه المتاجر المتاحة حالياً للزبائن في المجمع التجاري:"

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

# ==========================================
# 4. لوحة الإدارة الشاملة (Multi-Admin Panel)
# ==========================================
def send_admin_main(chat_id, message_id=None):
    db = load_db()
    stores = db.get("stores", {})
    markup = types.InlineKeyboardMarkup(row_width=1)

    if is_super_admin(chat_id):
        for s_id, s_info in stores.items():
            hide_status = " 🔒(مخفي حالياً)" if s_info.get("hidden", False) else ""
            markup.add(types.InlineKeyboardButton(f"🏬 إدارة وتعديل متجر: {s_info['name']}{hide_status}", callback_data=f"admin_store|{s_id}"))
        markup.add(types.InlineKeyboardButton("🛠️ لوحة التعديل السريع للمتاجر (الأسماء / الإخفاء / الحذف)", callback_data="admin_quick_stores"))
        markup.add(types.InlineKeyboardButton("➕ إنشاء متجر جديد في المجمع", callback_data="admin_add_store"))
    else:
        for s_id, s_info in stores.items():
            if str(s_info.get("admin_id", "")).strip() == str(chat_id):
                hide_status = " 🔒(مخفي حالياً)" if s_info.get("hidden", False) else ""
                markup.add(types.InlineKeyboardButton(f"🏬 إدارة وتعديل متجري: {s_info['name']}{hide_status}", callback_data=f"admin_store|{s_id}"))

    markup.add(
        types.InlineKeyboardButton("👁️ محاكاة ما يراه الزبون العادي (بدون المخفي)", callback_data="preview_customer"),
        types.InlineKeyboardButton("🔙 العودة للمول الرئيسي", callback_data="mall_home")
    )

    text = "👑 <b>لوحة تحكم الإدارة والمتاجر</b>\n\nاختر المتجر الذي ترغب بتعديله وإدارته (تغيير اسمه، إخفائه، أو إدارة منتجاته):"
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_admin_quick_stores(chat_id, message_id=None):
    if not is_super_admin(chat_id):
        return
    db = load_db()
    stores = db.get("stores", {})
    markup = types.InlineKeyboardMarkup(row_width=2)

    for s_id, s_info in stores.items():
        hide_btn = "🟢 إظهار المتجر" if s_info.get("hidden", False) else "👁️ إخفاء المتجر"
        s_name = s_info.get("name", s_id)
        markup.add(types.InlineKeyboardButton(f"🏬 {s_name}", callback_data=f"admin_store|{s_id}"))
        markup.add(
            types.InlineKeyboardButton("✏️ تغيير الاسم", callback_data=f"aset_name|{s_id}"),
            types.InlineKeyboardButton(hide_btn, callback_data=f"toggle_hide|{s_id}")
        )
        markup.add(
            types.InlineKeyboardButton("📋 استنساخ المتجر", callback_data=f"clone_store|{s_id}"),
            types.InlineKeyboardButton("🗑️ حذف المتجر", callback_data=f"confirm_del_store|{s_id}")
        )

    markup.add(types.InlineKeyboardButton("🔙 العودة للوحة الإدارة الرئيسية", callback_data="admin_main"))
    text = (
        "🛠️ <b>لوحة التعديل السريع لجميع المتاجر</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "يمكنك من هنا مباشرة تغيير أسماء المتاجر، أو إخفائها وإظهارها للزبائن، أو حذف أي متجر بضغطة زر:"
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_admin_store_panel(chat_id, store_id, message_id=None):
    if not is_store_admin(chat_id, store_id):
        bot.send_message(chat_id, "❌ لا تمتلك صلاحية إدارة هذا المتجر.")
        return

    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    hide_btn_text = "🟢 إظهار المتجر للزبائن (حالياً مخفي)" if store.get("hidden", False) else "👁️ إخفاء المتجر عن الزبائن (حالياً ظاهر)"
    markup.add(
        types.InlineKeyboardButton("✏️ تغيير اسم المتجر", callback_data=f"aset_name|{store_id}"),
        types.InlineKeyboardButton("💬 تغيير وصف المتجر", callback_data=f"aset_desc|{store_id}")
    )
    markup.add(types.InlineKeyboardButton(hide_btn_text, callback_data=f"toggle_hide|{store_id}"))
    markup.add(
        types.InlineKeyboardButton("📂 إدارة الأقسام", callback_data=f"admin_cats|{store_id}"),
        types.InlineKeyboardButton("📦 إدارة المنتجات", callback_data=f"admin_prods|{store_id}")
    )
    markup.add(
        types.InlineKeyboardButton("📊 إحصائيات وطلبات", callback_data=f"admin_stats|{store_id}"),
        types.InlineKeyboardButton("📢 إعلانات مجدولة للزبائن", callback_data=f"promo_panel|{store_id}")
    )
    markup.add(types.InlineKeyboardButton("⚙️ إعدادات / تعيين مدير", callback_data=f"admin_settings|{store_id}"))
    if is_super_admin(chat_id):
        markup.add(types.InlineKeyboardButton("🗑️ حذف هذا المتجر نهائياً", callback_data=f"confirm_del_store|{store_id}"))
    markup.add(
        types.InlineKeyboardButton("🔙 العودة لقائمة المتاجر", callback_data="admin_main"),
        types.InlineKeyboardButton("🏠 دخول المتجر كزبون", callback_data=f"open_store|{store_id}")
    )

    hide_lbl = "🔒 (مخفي حالياً عن الزبائن)" if store.get("hidden", False) else "🟢 (متاح وظاهر للزبائن)"
    text = (
        f"🛠️ <b>لوحة إدارة وتعديل: {store.get('name', 'المتجر')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 حالة الظهور: <b>{hide_lbl}</b>\n"
        f"💬 الوصف الحالي: <i>{store.get('desc', 'لا يوجد')}</i>\n"
        f"👥 عدد الأقسام الحالية: {len(store.get('categories', {}))}\n"
        f"📦 عدد المنتجات الحالية: {len(store.get('products', {}))}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 يمكنك مباشرة تغيير اسم المتجر، أو إخفائه وإظهاره، أو إدارة منتجاته وأقسامه من الأزرار أدناه:"
    )

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_admin_settings_panel(chat_id, store_id, message_id=None):
    if not is_store_admin(chat_id, store_id):
        return
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})

    sector = store.get("sector")
    if not sector:
        if store_id == "food_store":
            sector = "food"
        elif store_id == "cafe_store":
            sector = "cafe"
        else:
            sector = "shopping"

    del_mode = store.get("delivery_mode", "none" if sector == "cafe" else "paid" if store.get("delivery_fee", 0) > 0 else "free")
    if sector == "cafe":
        del_status = "🚫 غير متاح (خاص بالكافيهات - استلام/صالة فقط)"
    elif del_mode == "none":
        del_status = "🚫 لا يوجد توصيل (استلام/صالة فقط)"
    elif del_mode == "free":
        del_status = "🆓 توصيل خارجي مجاني"
    else:
        del_status = f"💰 توصيل بأجور ({format_price(store.get('delivery_fee', 0))})"

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ تغيير اسم المتجر", callback_data=f"aset_name|{store_id}"),
        types.InlineKeyboardButton("💬 تغيير وصف المتجر", callback_data=f"aset_desc|{store_id}")
    )
    if sector != "cafe":
        markup.add(
            types.InlineKeyboardButton(f"🛵 نظام التوصيل: {del_status}", callback_data=f"aset_delmode|{store_id}"),
            types.InlineKeyboardButton(f"💰 تعديل أجور التوصيل ({format_price(store.get('delivery_fee', 0))})", callback_data=f"aset_delfee|{store_id}")
        )
    markup.add(
        types.InlineKeyboardButton(f"📱 محفظة زين كاش ({store.get('wallet_number', 'غير محدد')[:12]})", callback_data=f"aset_wallet|{store_id}")
    )
    if is_super_admin(chat_id):
        admin_lbl = store.get("admin_id") or "الإدمن العام فقط"
        markup.add(types.InlineKeyboardButton(f"👤 تعيين مدير للمتجر (الحالي: {admin_lbl})", callback_data=f"aset_admin|{store_id}"))
    markup.add(types.InlineKeyboardButton("🔙 العودة لإدارة المتجر", callback_data=f"admin_store|{store_id}"))

    text = (
        f"⚙️ <b>إعدادات المتجر: {store.get('name', '')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ الاسم: {store.get('name', '')}\n"
        f"💬 الوصف: {store.get('desc', '')}\n"
        f"🛵 نظام التوصيل: {del_status}\n"
        f"💰 أجور التوصيل الحالية: {format_price(store.get('delivery_fee', 0))}\n"
        f"📱 محفظة زين كاش: <code>{store.get('wallet_number', 'غير محدد')}</code>\n"
        f"👤 المعرف المسؤول: <code>{store.get('admin_id') or 'الإدمن العام'}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 اختر الإعداد الذي ترغب بتعديله:"
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_delivery_mode_panel(chat_id, store_id, message_id=None):
    if not is_store_admin(chat_id, store_id):
        return
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🆓 توصيل خارجي مجاني (Free Delivery)", callback_data=f"setdel_free|{store_id}"),
        types.InlineKeyboardButton("💰 توصيل خارجي بأجور (Paid Delivery)", callback_data=f"setdel_paid|{store_id}"),
        types.InlineKeyboardButton("🚫 لا يوجد توصيل خارجي (استلام من الفرع / صالة فقط)", callback_data=f"setdel_none|{store_id}"),
        types.InlineKeyboardButton("🔙 العودة لإعدادات المتجر", callback_data=f"admin_settings|{store_id}")
    )
    text = (
        f"🛵 <b>تحديد نظام التوصيل الخارجي — «{store.get('name')}»</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"اختر كيف ترغب في تقديم خدمة التوصيل لزبائن متجرك:"
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

# ==========================================
# نظام الإعلانات الترويجية المجدولة والتلقائية (Promotional Broadcast System)
# ==========================================
def get_store_promo_terms(store):
    sec = store.get("sector", "")
    if sec in ["food", "cafe"]:
        return {
            "item_name": "الطبق / الصنف",
            "random_lbl": "🎲 اختيار طبق أو صنف عشوائي في كل بث",
            "icon": "🍕",
            "action_btn": "➕ أضف هذا الصنف لسلتك واطلبه الآن 🛒",
            "default_desc": "أشهى الأطباق والأصناف المميزة طازجة من أجلكم!",
            "store_lbl": "المطعم / الكافيه",
            "select_prompt": "🍕 اختر الطبق أو الصنف الذي تريد إرساله كإعلان:"
        }
    elif sec == "shopping":
        return {
            "item_name": "المنتج / السلعة",
            "random_lbl": "🎲 اختيار منتج عشوائي في كل بث",
            "icon": "🛍️",
            "action_btn": "➕ أضف هذا المنتج لسلتك واطلبه الآن 🛒",
            "default_desc": "منتجات وسلع عالية الجودة متوفرة الآن في متجرنا!",
            "store_lbl": "المتجر",
            "select_prompt": "🛍️ اختر المنتج الذي تريد إرساله كإعلان للزبائن:"
        }
    else:
        return {
            "item_name": "المنتج / الصنف",
            "random_lbl": "🎲 اختيار منتج/صنف عشوائي في كل بث",
            "icon": "📦",
            "action_btn": "➕ أضف هذا المنتج لسلتك واطلبه الآن 🛒",
            "default_desc": "منتجات وأصناف مميزة متوفرة الآن للطلب المباشر!",
            "store_lbl": "المتجر",
            "select_prompt": "📦 اختر المنتج أو الصنف الذي تريد إرساله كإعلان للزبائن:"
        }

def send_promo_panel(chat_id, store_id, message_id=None):
    if not is_store_admin(chat_id, store_id):
        return
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    promo = store.get("promo", {})
    terms = get_store_promo_terms(store)
    
    is_active = promo.get("active", False)
    interval_hours = promo.get("interval_hours", 24)
    product_id = promo.get("product_id", "random")
    
    status_lbl = "🟢 شغال (إرسال تلقائي)" if is_active else "🔴 متوقف حالياً"
    if product_id == "random" or product_id not in store.get("products", {}):
        prod_name = terms["random_lbl"]
    else:
        prod = store.get("products", {}).get(product_id, {})
        prod_name = f"🌟 {prod.get('name', terms['item_name'])}"
        
    markup = types.InlineKeyboardMarkup(row_width=1)
    toggle_text = "⏸️ إيقاف الإعلان التلقائي" if is_active else "▶️ تفعيل وتشغيل الإعلان التلقائي"
    markup.add(
        types.InlineKeyboardButton(f"⏱️ دورية التكرار: (كل {interval_hours} ساعة)", callback_data=f"promo_int_menu|{store_id}"),
        types.InlineKeyboardButton(f"{terms['icon']} {terms['item_name']} المعروض: ({prod_name[:22]})", callback_data=f"promo_prod_menu|{store_id}"),
        types.InlineKeyboardButton(toggle_text, callback_data=f"promo_toggle|{store_id}"),
        types.InlineKeyboardButton("📨 إرسال الإعلان للزبائن الآن (تجربة/بث فوري) 🚀", callback_data=f"promo_send_now|{store_id}"),
        types.InlineKeyboardButton("🔙 العودة لإدارة المتجر", callback_data=f"admin_store|{store_id}")
    )
    
    text = (
        f"📢 <b>نظام الإعلانات الترويجية المجدولة — «{store.get('name')}»</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>حالة البث التلقائي:</b> {status_lbl}\n"
        f"⏱️ <b>دورية الإرسال:</b> كل {interval_hours} ساعة\n"
        f"{terms['icon']} <b>{terms['item_name']} الإعلاني:</b> {prod_name}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>يقوم هذا النظام بإرسال بطاقة إعلانية جذابة بصورة {terms['item_name']} المختار مع زر للطلب السريع وإضافة للسلة مباشرة إلى شاشات جميع الزبائن تلقائياً كل مدة تحددها أنت!</i>\n\n"
        f"👇 تحكم بجدولة الإعلان أو أرسله فوراً من الأزرار أدناه:"
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_promo_broadcast(store_id, store, promo):
    db = load_db()
    users = set(db.get("users", []))
    for o in db.get("orders", {}).values():
        if o.get("chat_id"):
            users.add(o.get("chat_id"))
            
    terms = get_store_promo_terms(store)
    product_id = promo.get("product_id", "random")
    products = store.get("products", {})
    if not products or not users:
        return 0
        
    if product_id == "random" or product_id not in products:
        prod = random.choice(list(products.values()))
    else:
        prod = products[product_id]
        
    cat_id = prod.get("category_id") or (list(store.get("categories", {}).keys())[0] if store.get("categories") else "cat")
    
    old_p = prod.get("old_price", 0)
    if old_p > prod.get("price", 0):
        price_text = f"<s>{format_price(old_p)}</s> ➔ <b>{format_price(prod.get('price', 0))}</b> <i>(توفير مميز! 🔥)</i>"
    else:
        price_text = f"<code>{format_price(prod.get('price', 0))}</code>"

    caption = (
        f"🌟 <b>إعلان وترشيح مميز من: «{store.get('name', terms['store_lbl'])}»</b> 🌟\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{terms['icon']} <b>{prod.get('name')}</b>\n"
        f"💰 <b>السعر:</b> {price_text}"
    )
    
    img_url = (prod.get("image") or "").strip()
    sent_count = 0
    for u_id in users:
        try:
            if img_url:
                try:
                    bot.send_photo(u_id, img_url, caption=caption)
                    sent_count += 1
                    time.sleep(0.05)
                    continue
                except Exception:
                    pass
            bot.send_message(u_id, caption)
            sent_count += 1
            time.sleep(0.05)
        except Exception:
            pass
    return sent_count

def promo_scheduler_loop():
    while True:
        try:
            db = load_db()
            now = time.time()
            stores = db.get("stores", {})
            changed = False
            for s_id, store in stores.items():
                promo = store.get("promo", {})
                if promo.get("active") and promo.get("interval_hours", 0) > 0:
                    last_sent = promo.get("last_sent", 0)
                    interval_sec = promo.get("interval_hours", 24) * 3600
                    if now - last_sent >= interval_sec:
                        send_promo_broadcast(s_id, store, promo)
                        promo["last_sent"] = now
                        changed = True
            if changed:
                save_db(db)
        except Exception as e:
            print(f"[Promo Scheduler Error]: {e}")
        time.sleep(60)

def send_category_edit_panel(chat_id, store_id, cat_id, message_id=None):
    if not is_store_admin(chat_id, store_id):
        return
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    cat_name = store.get("categories", {}).get(cat_id)
    if not cat_name:
        bot.send_message(chat_id, "❌ القسم غير موجود.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ تعديل اسم القسم", callback_data=f"acat_ren|{store_id}|{cat_id}"),
        types.InlineKeyboardButton("🗑️ حذف القسم (مع منتجاته)", callback_data=f"acat_del|{store_id}|{cat_id}"),
        types.InlineKeyboardButton("🔙 العودة لقائمة الأقسام", callback_data=f"admin_cats|{store_id}")
    )
    text = f"📁 <b>إدارة القسم:</b> {cat_name}\n\nاختر الإجراء المطلوب من الأزرار أدناه:"
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_product_edit_panel(chat_id, store_id, prod_id, message_id=None):
    if not is_store_admin(chat_id, store_id):
        return
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    prod = store.get("products", {}).get(prod_id)
    if not prod:
        bot.send_message(chat_id, "❌ المنتج غير موجود.")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✏️ تعديل الاسم", callback_data=f"aprod_setname|{store_id}|{prod_id}"),
        types.InlineKeyboardButton("💰 تعديل السعر", callback_data=f"aprod_setprice|{store_id}|{prod_id}")
    )
    markup.add(
        types.InlineKeyboardButton("📝 تعديل الوصف", callback_data=f"aprod_setdesc|{store_id}|{prod_id}"),
        types.InlineKeyboardButton("🖼️ تعديل الصورة", callback_data=f"aprod_setimg|{store_id}|{prod_id}")
    )
    markup.add(
        types.InlineKeyboardButton("🏷️ إضافة/تعديل تخفيض (سعر قديم)", callback_data=f"aprod_setdisc|{store_id}|{prod_id}")
    )
    markup.add(types.InlineKeyboardButton("🗑️ حذف المنتج", callback_data=f"aprod_del|{store_id}|{prod_id}"))
    markup.add(types.InlineKeyboardButton("🔙 العودة لقائمة المنتجات", callback_data=f"admin_prods|{store_id}"))

    old_p = prod.get("old_price", 0)
    price_str = f"<s>{format_price(old_p)}</s> ➔ {format_price(prod.get('price', 0))}" if old_p > prod.get("price", 0) else format_price(prod.get("price", 0))

    text = (
        f"📦 <b>إدارة المنتج:</b> {prod.get('name', '')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 السعر الحالي: {price_str}\n"
        f"📝 الوصف: {prod.get('desc', '')}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 اختر الإجراء المطلوب:"
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_payment_selection(chat_id, store_id, extra_data, address_text):
    extra_data["address"] = address_text
    set_user_state(chat_id, "checkout_payment_sel", store_id, extra_data)
    text = (
        f"💳 <b>اختر طريقة الدفع المناسبة لك:</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"اختر كيف تفضل تسديد قيمة طلبك لتوثيقها في الفاتورة:"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💵 الدفع نقداً عند الاستلام", callback_data=f"pay|{store_id}|cash"),
        types.InlineKeyboardButton("📱 الدفع عبر زين كاش (ZainCash)", callback_data=f"pay|{store_id}|zaincash"),
        types.InlineKeyboardButton("💳 الدفع عبر بطاقة مصرفية (MasterCard/Qi)", callback_data=f"pay|{store_id}|card")
    )
    bot.send_message(chat_id, text, reply_markup=markup)

def finalize_order(chat_id, store_id, extra_data, address_text):
    cart = get_user_cart(chat_id, store_id)
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    total = sum(store["products"][pid]["price"] * qty for pid, qty in cart.items() if pid in store.get("products", {}))

    order_id = uuid.uuid4().hex[:8]
    order_type = extra_data.get("order_type", "🛍️ سفري (توصيل/خارجي)")
    is_dine_in = "صالة" in order_type

    delivery_fee = store.get("delivery_fee", 0) if not is_dine_in else 0
    final_total = total + delivery_fee

    order_data = {
        "id": order_id,
        "store_id": store_id,
        "chat_id": chat_id,
        "customer_name": extra_data.get("customer_name") or (f"زبون ({order_type})" if is_dine_in else "زبون"),
        "customer_phone": extra_data.get("customer_phone") or ("طلب داخل الصالة" if is_dine_in else "-"),
        "address": address_text,
        "order_type": order_type,
        "payment_method": extra_data.get("payment_method", "💵 الدفع نقداً"),
        "items": cart,
        "total_items": total,
        "delivery_fee": delivery_fee,
        "total": final_total,
        "status": "pending",
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    db["orders"][order_id] = order_data
    save_db(db)

    # تفريغ السلة وإرسال تأكيد للزبون
    user_carts[chat_id][store_id] = {}
    clear_user_state(chat_id)

    if is_dine_in:
        customer_msg = (
            f"🎉 <b>تم استلام طلبك بنجاح</b>\n"
            f"دقائق وطلبك يتم تجهيزه\n"
            f"شكراً لك لاختيارك «{store.get('name', 'متجرنا')}»\n"
            f"لا تنسى المعاوده مرة اخرى\n"
            f"نحن بأنتظارك\n"
            f"يكون مجموع الحساب هو : <b>{format_price(final_total)}</b>\n"
            f"💳 طريقة الدفع المحددة: {order_data['payment_method']}\n"
            f"رقم الطلب: <code>#{order_id}</code>"
        )
    else:
        customer_msg = (
            f"🎉 <b>تم استلام طلبك بنجاح! رقم الطلب: <code>#{order_id}</code></b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🍽️ <b>نوع الطلب: {order_type}</b>\n"
            f"👤 الاسم: {order_data['customer_name']}\n"
            f"📱 الهاتف: {order_data['customer_phone']}\n"
            f"📍 التفاصيل/الموقع: {order_data['address']}\n"
            f"💳 طريقة الدفع: {order_data['payment_method']}\n"
            f"💰 حساب المشتريات: <code>{format_price(total)}</code>\n"
            + (f"🛵 أجور التوصيل: <code>{format_price(delivery_fee)}</code>\n" if delivery_fee > 0 else "") +
            f"💵 الإجمالي الكلي المطلُوب: <code>{format_price(final_total)}</code>\n\n"
            f"⏳ <i>سيقوم فريق متجر «{store.get('name', '')}» بمراجعة طلبك وتجهيزه والتواصل معك قريباً!</i>"
        )

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("❌ إلغاء هذا الطلب (تعديل الطلب الآن)", callback_data=f"cancel_cust|{store_id}|{order_id}"),
        types.InlineKeyboardButton(f"🔙 العودة لأقسام {store.get('name', 'المتجر')} للتسوق", callback_data=f"open_store|{store_id}"),
        types.InlineKeyboardButton("🏬 العودة للمول الرئيسي", callback_data="mall_home")
    )
    bot.send_message(
        chat_id,
        customer_msg,
        reply_markup=markup
    )

    # إرسال إشعار فوري لمدير المتجر
    admin_id = store.get("admin_id") or SUPER_ADMIN_ID
    if admin_id:
        try:
            if is_dine_in:
                admin_text = (
                    f"🔔 <b>طلب صالة جديد في مطعمك! (#{order_id})</b>\n"
                    f"🏬 المطعم: {store.get('name')}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📍 <b>الموقع/الطاولة: {order_type}</b>\n"
                    f"💳 <b>طريقة الدفع:</b> {order_data['payment_method']}\n"
                    f"━━━━━━━━━━━━━━━━━━\n<b>📦 تفاصيل الأطباق والمنتجات المطلوبة:</b>\n"
                )
            else:
                admin_text = (
                    f"🔔 <b>طلب شراء جديد في متجرك! (#{order_id})</b>\n"
                    f"🏬 المتجر: {store.get('name')}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🍽️ <b>نوع الطلب: {order_type}</b>\n"
                    f"👤 المستلم/الزبون: {order_data['customer_name']}\n"
                    f"📱 الهاتف: <code>{order_data['customer_phone']}</code>\n"
                    f"📍 الموقع/التفاصيل: {order_data['address']}\n"
                    f"💳 <b>طريقة الدفع:</b> {order_data['payment_method']}\n"
                    f"━━━━━━━━━━━━━━━━━━\n<b>📦 تفاصيل المنتجات المطلوبة:</b>\n"
                )
            for pid, qty in cart.items():
                prod = store.get("products", {}).get(pid)
                if prod:
                    admin_text += f"▪️ {prod['name']} × ({qty}) = <code>{format_price(prod['price'] * qty)}</code>\n"
            admin_text += f"━━━━━━━━━━━━━━━━━━\n💰 <b>مجموع المشتريات: <code>{format_price(total)}</code></b>\n"
            if delivery_fee > 0:
                admin_text += f"🛵 <b>أجور التوصيل: <code>{format_price(delivery_fee)}</code></b>\n"
            admin_text += f"💵 <b>الإجمالي الكلي: <code>{format_price(final_total)}</code></b>"
            
            admin_markup = types.InlineKeyboardMarkup(row_width=2)
            admin_markup.add(
                types.InlineKeyboardButton("✅ قبول وتجهيز", callback_data=f"adm_acc|{store_id}|{order_id}"),
                types.InlineKeyboardButton("🚗 خرج للتوصيل", callback_data=f"adm_del|{store_id}|{order_id}")
            )
            admin_markup.add(
                types.InlineKeyboardButton("❌ رفض الطلب", callback_data=f"adm_rej|{store_id}|{order_id}")
            )
            
            # إرسال الصورة إن وجدت
            if "receipt_photo" in extra_data:
                bot.send_photo(admin_id, extra_data["receipt_photo"], caption=admin_text, reply_markup=admin_markup)
            else:
                bot.send_message(admin_id, admin_text, reply_markup=admin_markup)
        except Exception as e:
            print(f"[Error notifying admin]: {e}")

# ==========================================
# معالجة الأزرار التفاعلية (Callback Query Handler)
# ==========================================
if bot:
    @bot.callback_query_handler(func=lambda call: True)
    def handle_callbacks(call):
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        chat_id = call.message.chat.id
        data = call.data
        msg_id = call.message.message_id

        if data == "mall_home":
            clear_user_state(chat_id)
            send_mall_menu(chat_id, msg_id)

        elif data.startswith("open_sector|"):
            sector_key = data.split("|")[1]
            clear_user_state(chat_id)
            send_sector_stores(chat_id, sector_key, msg_id)

        elif data == "open_all_stores":
            clear_user_state(chat_id)
            send_all_stores(chat_id, msg_id)

        elif data.startswith("open_store|"):
            store_id = data.split("|")[1]
            clear_user_state(chat_id)
            send_store_home(chat_id, store_id, msg_id)

        elif data.startswith("cancel_cust|"):
            _, store_id, order_id = data.split("|")
            db = load_db()
            order = db.get("orders", {}).get(order_id)
            if order and order.get("status") == "pending" and str(order.get("chat_id")) == str(chat_id):
                order["status"] = "cancelled"
                save_db(db)
                bot.answer_callback_query(call.id, "✅ تم إلغاء طلبك بنجاح، يمكنك الآن اختيار طلب جديد!")
                store_obj = db.get("stores", {}).get(store_id, {})
                try:
                    bot.edit_message_text(f"❌ <b>تم إلغاء الطلب #{order_id} بناءً على طلبك.</b>\n\n👇 يمكنك الآن تصفح قائمة «{store_obj.get('name', 'المتجر')}» واختيار ما تحب:", chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass
                send_store_home(chat_id, store_id)
                # إشعار المدير بإلغاء الطلب
                store = db.get("stores", {}).get(store_id, {})
                admin_id = store.get("admin_id") or SUPER_ADMIN_ID
                if admin_id:
                    try:
                        bot.send_message(admin_id, f"⚠️ <b>تنبيه للمدير:</b>\nقام الزبون بإلغاء الطلب رقم <code>#{order_id}</code> الفوري الخاص بـ «{store.get('name')}»!")
                    except Exception:
                        pass
            else:
                bot.answer_callback_query(call.id, "❌ لا يمكن إلغاء هذا الطلب الآن (قد يكون قيد التجهيز أو تم إلغاؤه مسبقاً).", show_alert=True)

        elif data.startswith("open_cat|"):
            _, store_id, cat_id = data.split("|")
            send_category_products(chat_id, store_id, cat_id, msg_id)

        elif data.startswith("pos_nav|"):
            _, store_id, cat_id, idx_str = data.split("|")
            send_pos_card(chat_id, store_id, cat_id, int(idx_str), msg_id)

        elif data.startswith("pos_inc|") or data.startswith("pos_dec|"):
            parts = data.split("|")
            action = parts[0]
            store_id = parts[1]
            cat_id = parts[2]
            idx = int(parts[3])
            prod_id = parts[4]
            qty = 1 if action == "pos_inc" else -1
            add_to_cart(chat_id, store_id, prod_id, qty)
            bot.answer_callback_query(call.id, "🛒 تم تحديث الكمية في سلتك")
            send_pos_card(chat_id, store_id, cat_id, idx, msg_id, only_caption=True)

        elif data == "ignore_cb":
            bot.answer_callback_query(call.id)

        elif data.startswith("view_prod|"):
            _, store_id, prod_id = data.split("|")
            send_product_card(chat_id, store_id, prod_id, msg_id)

        elif data.startswith("view_cart|"):
            store_id = data.split("|")[1]
            send_cart_view(chat_id, store_id, msg_id)

        elif data.startswith("inc_cart|") or data.startswith("dec_cart|"):
            action, store_id, prod_id = data.split("|")
            qty = 1 if action == "inc_cart" else -1
            add_to_cart(chat_id, store_id, prod_id, qty)
            bot.answer_callback_query(call.id, "🛒 تم تحديث الكمية في سلتك")
            # تحديث الواجهة
            if call.message.caption:
                send_product_card(chat_id, store_id, prod_id, msg_id)
            else:
                send_cart_view(chat_id, store_id, msg_id)

        elif data.startswith("clear_cart|"):
            store_id = data.split("|")[1]
            if chat_id in user_carts and store_id in user_carts[chat_id]:
                user_carts[chat_id][store_id] = {}
            bot.answer_callback_query(call.id, "🗑️ تم تفريغ السلة بنجاح")
            send_cart_view(chat_id, store_id, msg_id)

        elif data.startswith("checkout|"):
            store_id = data.split("|")[1]
            cart = get_user_cart(chat_id, store_id)
            if not cart:
                bot.answer_callback_query(call.id, "❌ السلة فارغة!")
                return
            bot.answer_callback_query(call.id)
            db_temp = load_db()
            st_sec = db_temp.get("stores", {}).get(store_id, {}).get("sector")
            if not st_sec:
                if store_id == "food_store": st_sec = "food"
                elif store_id == "cafe_store": st_sec = "cafe"

            cur_type = get_user_order_type(chat_id, store_id)
            if st_sec in ["food", "cafe"] and not cur_type:
                send_order_type_selection(chat_id, store_id, msg_id, is_checkout=True)
            elif cur_type and "صالة" in cur_type:
                extra_data = {
                    "order_type": cur_type,
                    "customer_name": f"زبون الصالة ({cur_type})",
                    "customer_phone": "داخل الصالة"
                }
                send_payment_selection(chat_id, store_id, extra_data, address_text=cur_type)
            else:
                start_checkout_flow(chat_id, store_id, msg_id)

        elif data.startswith("choose_type_chk|") or data.startswith("choose_order_type|"):
            store_id = data.split("|")[1]
            is_chk = data.startswith("choose_type_chk|")
            send_order_type_selection(chat_id, store_id, msg_id, is_checkout=is_chk)

        elif data.startswith("choose_table|") or data.startswith("choose_table_chk|"):
            is_chk = data.startswith("choose_table_chk|")
            store_id = data.split("|")[1]
            send_table_selection(chat_id, store_id, msg_id, is_checkout=is_chk)

        elif data.startswith("set_takeaway|") or data.startswith("set_takeaway_chk|"):
            is_chk = data.startswith("set_takeaway_chk|")
            store_id = data.split("|")[1]
            db = load_db()
            st_obj = db.get("stores", {}).get(store_id, {})
            sec = st_obj.get("sector", "shopping")
            if sec == "cafe" or st_obj.get("delivery_mode") == "none":
                set_user_order_type(chat_id, store_id, "🚶 استلام مباشر من الفرع (بدون توصيل)")
                bot.answer_callback_query(call.id, "✅ تم اختيار: استلام مباشر من الفرع")
            else:
                set_user_order_type(chat_id, store_id, "🛍️ سفري (توصيل/خارجي)")
                bot.answer_callback_query(call.id, "✅ تم اختيار: طلب سفري (توصيل/خارجي)")
            if is_chk:
                start_checkout_flow(chat_id, store_id, msg_id)
            else:
                send_store_home(chat_id, store_id, msg_id)

        elif data.startswith("sel_table|") or data.startswith("sel_table_chk|"):
            parts = data.split("|")
            is_chk = parts[0] == "sel_table_chk"
            store_id = parts[1]
            table_num = parts[2]
            order_type_val = f"🍽️ صالة (طاولة رقم {table_num})"
            set_user_order_type(chat_id, store_id, order_type_val)
            bot.answer_callback_query(call.id, f"✅ تم تحديد الطاولة رقم: {table_num}")
            if is_chk:
                extra_data = {
                    "order_type": order_type_val,
                    "customer_name": f"زبون الصالة (طاولة رقم {table_num})",
                    "customer_phone": "داخل الصالة"
                }
                send_payment_selection(chat_id, store_id, extra_data, address_text=order_type_val)
            else:
                send_store_home(chat_id, store_id, msg_id)

        elif data.startswith("pay|"):
            parts = data.split("|")
            store_id = parts[1]
            pay_method = parts[2]
            
            methods_map = {
                "cash": "💵 الدفع نقداً عند الاستلام",
                "zaincash": "📱 زين كاش (ZainCash)",
                "card": "💳 بطاقة مصرفية (MasterCard/Qi Card)"
            }
            
            user_state = user_states.get(chat_id, {})
            if user_state.get("state") == "checkout_payment_sel" and user_state.get("store_id") == store_id:
                extra_data = user_state.get("data", {})
                extra_data["payment_method"] = methods_map.get(pay_method, "غير محدد")
                address_text = extra_data.get("address", "غير محدد")
                
                try:
                    bot.delete_message(chat_id, msg_id)
                except Exception:
                    pass
                bot.answer_callback_query(call.id, f"✅ تم اختيار طريقة الدفع: {extra_data['payment_method']}")
                
                if pay_method in ["zaincash", "card"]:
                    set_user_state(chat_id, "waiting_receipt", store_id, extra_data)
                    db = load_db()
                    wallet = db.get("stores", {}).get(store_id, {}).get("wallet_number", "لم يتم تحديد رقم (تواصل مع الإدارة)")
                    bot.send_message(
                        chat_id,
                        f"💳 <b>تأكيد الدفع الإلكتروني ({extra_data['payment_method']})</b>\n\n"
                        f"يرجى تحويل مبلغ الفاتورة إلى الحساب/الرقم التالي:\n"
                        f"<code>{wallet}</code>\n\n"
                        f"📸 <b>يرجى إرسال صورة (سكرين شوت) لوصل التحويل الآن في هذه الدردشة لإكمال طلبك.</b>",
                        reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("❌ إلغاء الطلب", callback_data=f"clear_cart|{store_id}"))
                    )
                else:
                    finalize_order(chat_id, store_id, extra_data, address_text)
            else:
                bot.answer_callback_query(call.id, "❌ انتهت صلاحية هذا الزر أو الطلب غير مكتمل.", show_alert=True)

        elif data.startswith("adm_acc|") or data.startswith("adm_del|") or data.startswith("adm_rej|"):
            action, store_id, order_id = data.split("|")
            db = load_db()
            order = db.get("orders", {}).get(order_id)
            if not order:
                bot.answer_callback_query(call.id, "❌ الطلب غير موجود أو تم حذفه.", show_alert=True)
                return
            
            customer_chat = order.get("chat_id")
            store_name = db.get("stores", {}).get(store_id, {}).get("name", "المتجر")
            
            try:
                if action == "adm_acc":
                    order["status"] = "accepted"
                    bot.send_message(customer_chat, f"✅ <b>تم قبول طلبك!</b>\nمتجر «{store_name}» يقوم الآن بتجهيز طلبك (رقم: #{order_id}).")
                    bot.answer_callback_query(call.id, "✅ تم تحديث الحالة وإشعار الزبون بالقبول.")
                elif action == "adm_del":
                    order["status"] = "delivered"
                    bot.send_message(customer_chat, f"🚗 <b>طلبك في الطريق!</b>\nطلبك من متجر «{store_name}» (رقم: #{order_id}) خرج للتوصيل.")
                    bot.answer_callback_query(call.id, "🚗 تم إشعار الزبون بالتوصيل.")
                elif action == "adm_rej":
                    order["status"] = "rejected"
                    bot.send_message(customer_chat, f"❌ <b>نعتذر، تم رفض/إلغاء طلبك.</b>\nمن قِبل متجر «{store_name}» (رقم: #{order_id}).")
                    bot.answer_callback_query(call.id, "❌ تم إلغاء الطلب وإشعار الزبون.")
                save_db(db)
                
                status_texts = {"adm_acc": "✅ (مقبول وقيد التجهيز)", "adm_del": "🚗 (خرج للتوصيل)", "adm_rej": "❌ (مرفوض/ملغي)"}
                old_text = call.message.caption or call.message.text
                if "\n\n🏷️ <b>تم تغيير الحالة إلى:</b>" in old_text:
                    old_text = old_text.split("\n\n🏷️ <b>تم تغيير الحالة إلى:</b>")[0]
                new_text = old_text + f"\n\n🏷️ <b>تم تغيير الحالة إلى:</b> {status_texts[action]}"
                if call.message.caption:
                    bot.edit_message_caption(new_text, chat_id=chat_id, message_id=msg_id)
                else:
                    bot.edit_message_text(new_text, chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                bot.answer_callback_query(call.id, "حدث خطأ في المراسلة.", show_alert=True)

        # أوامر الإدارة
        elif data == "preview_customer":
            send_customer_preview(chat_id, msg_id)
        elif data.startswith("prev_sec|"):
            send_customer_preview_sector(chat_id, data.split("|")[1], msg_id)
        elif data == "prev_all":
            send_customer_preview_all(chat_id, msg_id)

        elif data == "my_orders":
            send_my_orders(chat_id, msg_id)

        elif data == "admin_main":
            send_admin_main(chat_id, msg_id)

        elif data == "admin_quick_stores":
            send_admin_quick_stores(chat_id, msg_id)

        elif data.startswith("admin_store|"):
            store_id = data.split("|")[1]
            send_admin_store_panel(chat_id, store_id, msg_id)

        elif data.startswith("confirm_del_store|"):
            store_id = data.split("|")[1]
            if not is_super_admin(chat_id):
                bot.answer_callback_query(call.id, "❌ هذا الإجراء متاح للإدمن العام فقط.", show_alert=True)
                return
            db = load_db()
            s_name = db.get("stores", {}).get(store_id, {}).get("name", store_id)
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("🗑️ نعم، احذف نهائياً", callback_data=f"del_store|{store_id}"),
                types.InlineKeyboardButton("❌ إلغاء والتراجع", callback_data=f"admin_store|{store_id}")
            )
            text = f"⚠️ <b>تأكيد حذف المتجر</b>\n\nهل أنت متأكد من رغبتك بحذف متجر «<b>{s_name}</b>» نهائياً مع جميع أقسامه ومنتجاته؟"
            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=markup)

        elif data.startswith("del_store|"):
            store_id = data.split("|")[1]
            if not is_super_admin(chat_id):
                bot.answer_callback_query(call.id, "❌ هذا الإجراء متاح للإدمن العام فقط.", show_alert=True)
                return
            db = load_db()
            if store_id in db.get("stores", {}):
                s_name = db["stores"].pop(store_id).get("name", store_id)
                save_db(db)
                bot.answer_callback_query(call.id, f"🗑️ تم حذف متجر «{s_name}» بنجاح!", show_alert=True)
            send_admin_main(chat_id, msg_id)

        elif data.startswith("toggle_hide|"):
            store_id = data.split("|")[1]
            if is_store_admin(chat_id, store_id):
                db = load_db()
                if store_id in db.get("stores", {}):
                    current_hidden = db["stores"][store_id].get("hidden", False)
                    db["stores"][store_id]["hidden"] = not current_hidden
                    save_db(db)
                    status_text = "🔒 تم إخفاء المتجر عن رؤية الزبائن بنجاح!" if not current_hidden else "🟢 تم إظهار المتجر وأصبح متاحاً للزبائن الآن!"
                    bot.answer_callback_query(call.id, status_text, show_alert=True)
                    send_admin_store_panel(chat_id, store_id, msg_id)

        elif data.startswith("admin_cats|"):
            store_id = data.split("|")[1]
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            markup = types.InlineKeyboardMarkup(row_width=1)
            for c_id, c_name in store.get("categories", {}).items():
                markup.add(types.InlineKeyboardButton(f"📁 {c_name} (تعديل/حذف)", callback_data=f"acat_edit|{store_id}|{c_id}"))
            markup.add(
                types.InlineKeyboardButton("➕ إضافة قسم جديد", callback_data=f"acat_add|{store_id}"),
                types.InlineKeyboardButton("🔙 العودة لإدارة المتجر", callback_data=f"admin_store|{store_id}")
            )
            bot.edit_message_text(f"📂 <b>إدارة أقسام: {store['name']}</b>\n\nاختر قسماً لتعديله أو اختر إضافة قسم جديد:", chat_id=chat_id, message_id=msg_id, reply_markup=markup)

        elif data.startswith("acat_add|"):
            store_id = data.split("|")[1]
            set_user_state(chat_id, "waiting_cat_add", store_id)
            bot.send_message(chat_id, "✏️ أرسل الآن <b>اسم القسم الجديد</b> الذي ترغب بإضافته لهذا المتجر في رسالة:")

        elif data.startswith("admin_prods|"):
            store_id = data.split("|")[1]
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            markup = types.InlineKeyboardMarkup(row_width=1)
            for p_id, p_info in store.get("products", {}).items():
                markup.add(types.InlineKeyboardButton(f"📦 {p_info['name']} - ({format_price(p_info['price'])})", callback_data=f"aprod_edit|{store_id}|{p_id}"))
            markup.add(
                types.InlineKeyboardButton("➕ إضافة منتج جديد", callback_data=f"aprod_add|{store_id}"),
                types.InlineKeyboardButton("🔙 العودة لإدارة المتجر", callback_data=f"admin_store|{store_id}")
            )
            bot.edit_message_text(f"📦 <b>إدارة منتجات: {store['name']}</b>\n\nاختر منتجاً لتعديله/حذفه أو اضغط إضافة منتج:", chat_id=chat_id, message_id=msg_id, reply_markup=markup)

        elif data.startswith("aprod_add|"):
            store_id = data.split("|")[1]
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            if not store.get("categories"):
                bot.send_message(chat_id, "❌ يجب إضافة قسم واحد على الأقل قبل إضافة المنتجات.")
                return
            markup = types.InlineKeyboardMarkup(row_width=1)
            for c_id, c_name in store["categories"].items():
                markup.add(types.InlineKeyboardButton(f"📁 {c_name}", callback_data=f"aprod_selcat|{store_id}|{c_id}"))
            bot.edit_message_text("➕ <b>إضافة منتج جديد:</b>\nاختر القسم الذي سينتمي إليه هذا المنتج أولاً:", chat_id=chat_id, message_id=msg_id, reply_markup=markup)

        elif data.startswith("aprod_selcat|"):
            _, store_id, cat_id = data.split("|")
            set_user_state(chat_id, "waiting_prod_name", store_id, {"category_id": cat_id})
            bot.send_message(chat_id, "✏️ أرسل الآن <b>اسم المنتج</b> الذي ترغب بإضافته:\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("admin_settings|"):
            store_id = data.split("|")[1]
            send_admin_settings_panel(chat_id, store_id, msg_id)

        elif data.startswith("clone_store|"):
            store_id = data.split("|")[1]
            if not is_super_admin(chat_id):
                bot.answer_callback_query(call.id, "❌ استنساخ المتاجر متاح للإدمن العام فقط.", show_alert=True)
                return
            set_user_state(chat_id, "waiting_clone_name", store_id)
            bot.send_message(chat_id, "📋 <b>استنساخ المتجر (إنشاء نسخة مستقلة لعميل جديد):</b>\n✏️ أرسل الآن <b>اسم المتجر أو المطعم الجديد</b> في رسالة (مثلاً: مطعم بيتزا رماح أو فرع المنصور):\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("aset_sector|"):
            store_id = data.split("|")[1]
            send_sector_change_panel(chat_id, store_id, msg_id)

        elif data.startswith("set_sec|"):
            _, store_id, sec_key = data.split("|")
            if is_store_admin(chat_id, store_id):
                db = load_db()
                if store_id in db.get("stores", {}):
                    db["stores"][store_id]["sector"] = sec_key
                    save_db(db)
                    bot.answer_callback_query(call.id, "✅ تم نقل وتصنيف المتجر للجناح المحدد بنجاح!", show_alert=True)
                send_admin_settings_panel(chat_id, store_id, msg_id)

        elif data.startswith("aset_name|"):
            store_id = data.split("|")[1]
            set_user_state(chat_id, "waiting_store_name", store_id)
            bot.send_message(chat_id, "✏️ أرسل الآن <b>الاسم الجديد</b> لهذا المتجر في رسالة:\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("aset_desc|"):
            store_id = data.split("|")[1]
            set_user_state(chat_id, "waiting_store_desc", store_id)
            bot.send_message(chat_id, "💬 أرسل الآن <b>الوصف الجديد</b> لهذا المتجر في رسالة:\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("aset_delfee|"):
            store_id = data.split("|")[1]
            set_user_state(chat_id, "waiting_delivery_fee", store_id)
            bot.send_message(chat_id, "🛵 أرسل الآن <b>أجور التوصيل بالدينار العراقي</b> لهذا المتجر (أو أرسل 0 للتوصيل المجاني):\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("aset_delmode|"):
            store_id = data.split("|")[1]
            send_delivery_mode_panel(chat_id, store_id, msg_id)

        elif data.startswith("setdel_free|"):
            store_id = data.split("|")[1]
            if is_store_admin(chat_id, store_id):
                db = load_db()
                if store_id in db.get("stores", {}):
                    db["stores"][store_id]["delivery_mode"] = "free"
                    db["stores"][store_id]["delivery_fee"] = 0
                    save_db(db)
                bot.answer_callback_query(call.id, "✅ تم تعيين التوصيل: مجاني لكل الزبائن")
                send_admin_settings_panel(chat_id, store_id, msg_id)

        elif data.startswith("setdel_none|"):
            store_id = data.split("|")[1]
            if is_store_admin(chat_id, store_id):
                db = load_db()
                if store_id in db.get("stores", {}):
                    db["stores"][store_id]["delivery_mode"] = "none"
                    db["stores"][store_id]["delivery_fee"] = 0
                    save_db(db)
                bot.answer_callback_query(call.id, "✅ تم إلغاء خدمة التوصيل (استلام من الفرع فقط)")
                send_admin_settings_panel(chat_id, store_id, msg_id)

        elif data.startswith("setdel_paid|"):
            store_id = data.split("|")[1]
            if is_store_admin(chat_id, store_id):
                db = load_db()
                if store_id in db.get("stores", {}):
                    db["stores"][store_id]["delivery_mode"] = "paid"
                    save_db(db)
                set_user_state(chat_id, "waiting_delivery_fee", store_id)
                bot.send_message(chat_id, "💰 أرسل الآن مبلغ أجور التوصيل بالدينار العراقي (مثلاً 3000):")

        elif data.startswith("aset_wallet|"):
            store_id = data.split("|")[1]
            set_user_state(chat_id, "waiting_wallet_number", store_id)
            bot.send_message(chat_id, "📱 أرسل الآن <b>رقم محفظة زين كاش أو الحساب المصرفي</b> لهذا المتجر ليتم عرضه للزبائن عند اختيار الدفع الإلكتروني:\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("aset_admin|"):
            store_id = data.split("|")[1]
            set_user_state(chat_id, "waiting_store_admin", store_id)
            bot.send_message(chat_id, "👤 أرسل الآن <b>الـ Telegram ID</b> لمدير هذا المتجر (أو أرسل 0 لإزالة المدير الحالي والاكتفاء بالإدمن العام):\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("acat_edit|"):
            _, store_id, cat_id = data.split("|")
            send_category_edit_panel(chat_id, store_id, cat_id, msg_id)

        elif data.startswith("acat_ren|"):
            _, store_id, cat_id = data.split("|")
            set_user_state(chat_id, "waiting_cat_rename", store_id, {"category_id": cat_id})
            bot.send_message(chat_id, "✏️ أرسل الآن <b>الاسم الجديد للقسم</b> في رسالة:\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("acat_del|"):
            _, store_id, cat_id = data.split("|")
            if is_store_admin(chat_id, store_id):
                db = load_db()
                store = db.get("stores", {}).get(store_id, {})
                if cat_id in store.get("categories", {}):
                    cat_name = store["categories"].pop(cat_id)
                    # حذف المنتجات التابعة لهذا القسم أيضا
                    prods_to_del = [pid for pid, p in store.get("products", {}).items() if p.get("category_id") == cat_id]
                    for pid in prods_to_del:
                        store["products"].pop(pid, None)
                    save_db(db)
                    bot.send_message(chat_id, f"🗑️ تم حذف القسم «{cat_name}» وجميع منتجاته بنجاح!")
                send_admin_store_panel(chat_id, store_id, msg_id)

        elif data.startswith("aprod_edit|"):
            _, store_id, prod_id = data.split("|")
            send_product_edit_panel(chat_id, store_id, prod_id, msg_id)

        elif data.startswith("aprod_setname|"):
            _, store_id, prod_id = data.split("|")
            set_user_state(chat_id, "waiting_prod_rename", store_id, {"prod_id": prod_id})
            bot.send_message(chat_id, "✏️ أرسل الآن <b>الاسم الجديد للمنتج</b>:\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("aprod_setprice|"):
            _, store_id, prod_id = data.split("|")
            set_user_state(chat_id, "waiting_prod_reprice", store_id, {"prod_id": prod_id})
            bot.send_message(chat_id, "💰 أرسل الآن <b>السعر الجديد للمنتج</b> (أرقام فقط):\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("aprod_setdisc|"):
            _, store_id, prod_id = data.split("|")
            set_user_state(chat_id, "waiting_prod_redisc", store_id, {"prod_id": prod_id})
            bot.send_message(chat_id, "🏷️ أرسل الآن <b>السعر الأصلي (القديم) قبل التخفيض</b> ليتم شطبه وإظهاره للزبون (أو أرسل <b>0</b> لإلغاء التخفيض الحالي):\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("aprod_setdesc|"):
            _, store_id, prod_id = data.split("|")
            set_user_state(chat_id, "waiting_prod_redesc", store_id, {"prod_id": prod_id})
            bot.send_message(chat_id, "📝 أرسل الآن <b>الوصف الجديد للمنتج</b>:\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("aprod_setimg|"):
            _, store_id, prod_id = data.split("|")
            set_user_state(chat_id, "waiting_prod_reimg", store_id, {"prod_id": prod_id})
            bot.send_message(chat_id, "🖼️ أرسل الآن <b>صورة المنتج</b> (يمكنك إرسال صورة مباشرة من هاتفك، أو رابط صورة على الإنترنت)، أو أرسل <b>0</b> لإزالة الصورة الحالية من المنتج:\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("aprod_del|"):
            _, store_id, prod_id = data.split("|")
            if is_store_admin(chat_id, store_id):
                db = load_db()
                store = db.get("stores", {}).get(store_id, {})
                if prod_id in store.get("products", {}):
                    p_name = store["products"].pop(prod_id).get("name", "")
                    save_db(db)
                    bot.send_message(chat_id, f"🗑️ تم حذف المنتج «{p_name}» بنجاح!")
                send_admin_store_panel(chat_id, store_id, msg_id)

        elif data == "admin_add_store" and is_super_admin(chat_id):
            set_user_state(chat_id, "waiting_new_store_name")
            bot.send_message(chat_id, "🏬 أرسل الآن <b>اسم المتجر الجديد</b> الذي ترغب بإضافته للمجمع التجاري:\n\n*(أو أرسل /cancel للإلغاء)*")

        elif data.startswith("admin_stats|"):
            store_id = data.split("|")[1]
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            orders = [o for o in db.get("orders", {}).values() if o.get("store_id") == store_id]
            
            completed_orders = [o for o in orders if o.get("status") == "delivered"]
            total_rev = sum(o.get("total", 0) for o in completed_orders)
            
            pending_cnt = len([o for o in orders if o.get("status") == "pending"])
            accepted_cnt = len([o for o in orders if o.get("status") == "accepted"])
            delivered_cnt = len(completed_orders)
            cancelled_cnt = len([o for o in orders if o.get("status") in ["cancelled", "rejected"]])
            
            # Average order value
            aov = (total_rev / len(completed_orders)) if completed_orders else 0
            
            # Periodic sales
            import datetime
            now = datetime.datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            
            sales_today = 0
            sales_week = 0
            sales_month = 0
            
            for o in completed_orders:
                o_time_str = o.get("time", "")
                try:
                    o_time = datetime.datetime.strptime(o_time_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    o_time = now
                
                # Check periods
                diff = now - o_time
                if o_time_str.startswith(today_str):
                    sales_today += o.get("total", 0)
                if diff.days < 7:
                    sales_week += o.get("total", 0)
                if diff.days < 30:
                    sales_month += o.get("total", 0)
            
            # Top-selling products
            product_sales = {}
            for o in completed_orders:
                for pid, qty in o.get("items", {}).items():
                    product_sales[pid] = product_sales.get(pid, 0) + qty
                    
            sorted_prods = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)
            top_selling = []
            for pid, qty in sorted_prods[:3]:
                prod_name = store.get("products", {}).get(pid, {}).get("name", f"منتج #{pid}")
                top_selling.append(f"▪️ {prod_name}: تم بيع ({qty})")
                
            top_selling_text = "\n".join(top_selling) if top_selling else "لا توجد مبيعات منتجات بعد."
            
            text = (
                f"📊 <b>التقرير الإحصائي وإدارة المبيعات: {store.get('name')}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 <b>إجمالي الإيرادات (المكتملة):</b> <code>{format_price(total_rev)}</code>\n"
                f"📦 <b>إجمالي الطلبات المستلمة:</b> {len(orders)} طلب\n"
                f"⚖️ <b>متوسط قيمة الطلب الواحد:</b> <code>{format_price(aov)}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⏳ قيد الانتظار: <b>{pending_cnt}</b> | ✅ مقبول وتجهيز: <b>{accepted_cnt}</b>\n"
                f"🚗 تم التوصيل: <b>{delivered_cnt}</b> | ❌ مرفوض وملغي: <b>{cancelled_cnt}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📅 <b>مبيعات اليوم:</b> <code>{format_price(sales_today)}</code>\n"
                f"📅 <b>مبيعات آخر 7 أيام:</b> <code>{format_price(sales_week)}</code>\n"
                f"📅 <b>مبيعات آخر 30 يوماً:</b> <code>{format_price(sales_month)}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🔥 <b>الأكثر مبيعاً:</b>\n{top_selling_text}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
            )
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("📋 الطلبات النشطة", callback_data=f"admin_manage_orders|{store_id}|0"),
                types.InlineKeyboardButton("📥 تصدير ملف المبيعات", callback_data=f"export_sales_csv|{store_id}")
            )
            markup.add(types.InlineKeyboardButton("🔙 العودة لإدارة المتجر", callback_data=f"admin_store|{store_id}"))
            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=markup)

        elif data.startswith("admin_manage_orders|"):
            parts = data.split("|")
            store_id = parts[1]
            page = int(parts[2])
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            orders = [o for o in db.get("orders", {}).values() if o.get("store_id") == store_id and o.get("status") in ["pending", "accepted"]]
            orders = sorted(orders, key=lambda x: x.get("time", ""), reverse=True)
            
            per_page = 5
            total_pages = (len(orders) + per_page - 1) // per_page if orders else 1
            page = max(0, min(page, total_pages - 1))
            page_orders = orders[page * per_page : (page + 1) * per_page]
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            for o in page_orders:
                o_id = o['id']
                stat_lbl = "⏳ قيد الانتظار" if o['status'] == 'pending' else "✅ قيد التجهيز"
                btn_txt = f"📦 #{o_id} - {o['customer_name']} ({format_price(o['total'])}) [{stat_lbl}]"
                markup.add(types.InlineKeyboardButton(btn_txt, callback_data=f"admin_order_det|{store_id}|{o_id}"))
                
            nav_buttons = []
            if page > 0:
                nav_buttons.append(types.InlineKeyboardButton("⬅️ السابق", callback_data=f"admin_manage_orders|{store_id}|{page-1}"))
            if page < total_pages - 1:
                nav_buttons.append(types.InlineKeyboardButton("التالي ➡️", callback_data=f"admin_manage_orders|{store_id}|{page+1}"))
            if nav_buttons:
                markup.row(*nav_buttons)
                
            markup.add(
                types.InlineKeyboardButton("🔄 تحديث القائمة", callback_data=f"admin_manage_orders|{store_id}|{page}"),
                types.InlineKeyboardButton("🔙 العودة للإحصائيات", callback_data=f"admin_stats|{store_id}")
            )
            
            text = (
                f"📋 <b>إدارة الطلبات النشطة: {store.get('name')}</b>\n"
                f"الصحفة: {page+1} من {total_pages}\n\n"
                f"اضغط على أي طلب من القائمة أدناه لاستعراض كامل تفاصيله، أو قبوله وتغيير حالته:"
            )
            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=markup)

        elif data.startswith("admin_order_det|"):
            _, store_id, order_id = data.split("|")
            db = load_db()
            order = db.get("orders", {}).get(order_id)
            if not order:
                bot.answer_callback_query(call.id, "❌ الطلب غير موجود.", show_alert=True)
                return
            
            store = db.get("stores", {}).get(store_id, {})
            status_map = {"pending": "⏳ قيد الانتظار", "accepted": "✅ مقبول وقيد التجهيز", "delivered": "🚗 تم التسليم والانتهاء", "rejected": "❌ مرفوض وملغي"}
            
            text = (
                f"📄 <b>تفاصيل الطلب: #{order_id}</b>\n"
                f"🏬 المتجر: {store.get('name')}\n"
                f"📅 التاريخ: {order.get('time')}\n"
                f"🏷️ الحالة الحالية: <b>{status_map.get(order.get('status'), 'غير معروف')}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👤 العميل: {order.get('customer_name')}\n"
                f"📱 الهاتف: <code>{order.get('customer_phone')}</code>\n"
                f"📍 العنوان/الموقع: {order.get('address')}\n"
                f"🍽️ النوع: {order.get('order_type')}\n"
                f"💳 الدفع: {order.get('payment_method')}\n"
                f"━━━━━━━━━━━━━━━━━━\n<b>📦 المنتجات المطلوبة:</b>\n"
            )
            for pid, qty in order.get("items", {}).items():
                p_info = store.get("products", {}).get(pid, {})
                if p_info:
                    text += f"▪️ {p_info['name']} × ({qty}) = <code>{format_price(p_info['price'] * qty)}</code>\n"
            text += f"━━━━━━━━━━━━━━━━━━\n💵 <b>الإجمالي الكلي: {format_price(order.get('total'))}</b>"
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            if order.get("status") == "pending":
                markup.add(
                    types.InlineKeyboardButton("✅ قبول وتجهيز", callback_data=f"adm_acc|{store_id}|{order_id}"),
                    types.InlineKeyboardButton("❌ رفض وإلغاء", callback_data=f"adm_rej|{store_id}|{order_id}")
                )
            elif order.get("status") == "accepted":
                markup.add(
                    types.InlineKeyboardButton("🚗 خرج للتوصيل", callback_data=f"adm_del|{store_id}|{order_id}"),
                    types.InlineKeyboardButton("❌ رفض وإلغاء", callback_data=f"adm_rej|{store_id}|{order_id}")
                )
            markup.add(types.InlineKeyboardButton("🔙 العودة لقائمة الطلبات", callback_data=f"admin_manage_orders|{store_id}|0"))
            
            if order.get("receipt_photo"):
                try:
                    bot.delete_message(chat_id, msg_id)
                except Exception:
                    pass
                bot.send_photo(chat_id, order.get("receipt_photo"), caption=text, reply_markup=markup)
            else:
                bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=markup)

        elif data.startswith("export_sales_csv|"):
            store_id = data.split("|")[1]
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            orders = [o for o in db.get("orders", {}).values() if o.get("store_id") == store_id]
            
            if not orders:
                bot.answer_callback_query(call.id, "❌ لا توجد أي مبيعات أو طلبات لتصديرها لهذا المتجر بعد.", show_alert=True)
                return
                
            bot.answer_callback_query(call.id, "⏳ جاري إنشاء تقرير المبيعات...")
            
            import csv
            import io
            
            output = io.StringIO()
            output.write('\ufeff')
            writer = csv.writer(output, delimiter=',')
            writer.writerow(['رقم الطلب', 'تاريخ الطلب', 'اسم الزبون', 'رقم الهاتف', 'العنوان والموقع', 'نوع الطلب', 'طريقة الدفع', 'الحالة', 'مجموع الحساب'])
            
            status_map = {"pending": "قيد الانتظار", "accepted": "قيد التجهيز", "delivered": "تم التسليم", "rejected": "مرفوض/ملغي", "cancelled": "ملغي من الزبون"}
            for o in orders:
                writer.writerow([
                    o.get('id', ''),
                    o.get('time', ''),
                    o.get('customer_name', ''),
                    o.get('customer_phone', ''),
                    o.get('address', '').replace('\n', ' '),
                    o.get('order_type', ''),
                    o.get('payment_method', ''),
                    status_map.get(o.get('status', ''), o.get('status', '')),
                    f"{o.get('total', 0)} د.ع"
                ])
                
            csv_data = output.getvalue()
            output.close()
            
            file_bytes = csv_data.encode('utf-8-sig')
            bio = io.BytesIO(file_bytes)
            bio.name = f"sales_report_{store_id}.csv"
            
            import datetime
            bot.send_document(
                chat_id,
                bio,
                caption=f"📊 <b>تقرير مبيعات وطلبات متجر: {store.get('name')}</b>\n\nتاريخ التصدير: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

        elif data.startswith("promo_panel|"):
            store_id = data.split("|")[1]
            send_promo_panel(chat_id, store_id, msg_id)

        elif data.startswith("promo_int_menu|"):
            store_id = data.split("|")[1]
            markup = types.InlineKeyboardMarkup(row_width=2)
            for hrs, lbl in [(6, "6 ساعات"), (12, "12 ساعة"), (24, "يومياً (24 ساعة)"), (48, "كل يومين"), (168, "أسبوعياً")]:
                markup.add(types.InlineKeyboardButton(f"⏱️ {lbl}", callback_data=f"promo_set_int|{store_id}|{hrs}"))
            markup.add(types.InlineKeyboardButton("🔙 العودة للوحة الإعلانات", callback_data=f"promo_panel|{store_id}"))
            bot.edit_message_text("⏱️ <b>اختر المدة الزمنية لتكرار إرسال الإعلان الترويجي للزبائن:</b>", chat_id=chat_id, message_id=msg_id, reply_markup=markup)

        elif data.startswith("promo_set_int|"):
            _, store_id, hrs_str = data.split("|")
            db = load_db()
            if store_id in db.get("stores", {}):
                if "promo" not in db["stores"][store_id]:
                    db["stores"][store_id]["promo"] = {}
                db["stores"][store_id]["promo"]["interval_hours"] = int(hrs_str)
                save_db(db)
                bot.answer_callback_query(call.id, f"✅ تم تحديد التكرار كل {hrs_str} ساعة بنجاح!")
            send_promo_panel(chat_id, store_id, msg_id)

        elif data.startswith("promo_prod_menu|"):
            store_id = data.split("|")[1]
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            terms = get_store_promo_terms(store)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton(terms['random_lbl'], callback_data=f"promo_set_prod|{store_id}|random"))
            for p_id, p_info in store.get("products", {}).items():
                markup.add(types.InlineKeyboardButton(f"{terms['icon']} {p_info['name']} - ({format_price(p_info['price'])})", callback_data=f"promo_set_prod|{store_id}|{p_id}"))
            markup.add(types.InlineKeyboardButton("🔙 العودة للوحة الإعلانات", callback_data=f"promo_panel|{store_id}"))
            bot.edit_message_text(f"{terms['select_prompt']}\n*(أو اختر عشوائي ليتغير في كل إرسال)*", chat_id=chat_id, message_id=msg_id, reply_markup=markup)

        elif data.startswith("promo_set_prod|"):
            _, store_id, p_id = data.split("|")
            db = load_db()
            if store_id in db.get("stores", {}):
                if "promo" not in db["stores"][store_id]:
                    db["stores"][store_id]["promo"] = {}
                db["stores"][store_id]["promo"]["product_id"] = p_id
                save_db(db)
                terms = get_store_promo_terms(db["stores"][store_id])
                bot.answer_callback_query(call.id, f"✅ تم تحديد {terms['item_name']} الترويجي بنجاح!")
            send_promo_panel(chat_id, store_id, msg_id)

        elif data.startswith("promo_toggle|"):
            store_id = data.split("|")[1]
            db = load_db()
            if store_id in db.get("stores", {}):
                if "promo" not in db["stores"][store_id]:
                    db["stores"][store_id]["promo"] = {"interval_hours": 24, "product_id": "random", "last_sent": 0}
                cur = db["stores"][store_id]["promo"].get("active", False)
                db["stores"][store_id]["promo"]["active"] = not cur
                if not cur:
                    db["stores"][store_id]["promo"]["last_sent"] = time.time()
                save_db(db)
                lbl = "تشغيل 🟢" if not cur else "إيقاف 🔴"
                bot.answer_callback_query(call.id, f"✅ تم {lbl} الإعلانات التلقائية بنجاح!")
            send_promo_panel(chat_id, store_id, msg_id)

        elif data.startswith("promo_send_now|"):
            store_id = data.split("|")[1]
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            promo = store.get("promo", {})
            bot.answer_callback_query(call.id, "⏳ جارٍ إرسال البث الإعلاني لجميع الزبائن الآن...")
            count = send_promo_broadcast(store_id, store, promo)
            if store_id in db.get("stores", {}):
                if "promo" not in db["stores"][store_id]:
                    db["stores"][store_id]["promo"] = {}
                db["stores"][store_id]["promo"]["last_sent"] = time.time()
                save_db(db)
            bot.send_message(chat_id, f"🚀 <b>تم إرسال الإعلان الترويجي لـ ({count}) زبون بنجاح!</b>")
            send_promo_panel(chat_id, store_id, msg_id)

    @bot.message_handler(commands=['start', 'mall'])
    def handle_start(message):
        chat_id = message.chat.id
        register_user(chat_id)
        clear_user_state(chat_id)
        send_mall_menu(chat_id)

    @bot.message_handler(commands=['id', 'myid'])
    def handle_id(message):
        bot.reply_to(message, f"🆔 <b>معرفك الشخصي (Telegram ID) هو:</b> <code>{message.chat.id}</code>\n\nانسخه وضعه داخل ملف <b>.env</b> في متغير <b>SUPER_ADMIN_ID</b> لتفعيل صلاحيات الإدارة الكاملة لك!")

    @bot.message_handler(commands=['admin'])
    def handle_admin(message):
        chat_id = message.chat.id
        clear_user_state(chat_id)
        send_admin_main(chat_id)

    @bot.message_handler(content_types=['text', 'photo', 'location'])
    def handle_messages(message):
        chat_id = message.chat.id
        state_info = user_states.get(chat_id, {})
        state = state_info.get("state", "menu")
        store_id = state_info.get("store_id")
        extra_data = state_info.get("data", {})

        text_lower = (message.text or "").strip().lower()
        if text_lower in ["id", "myid", "ايدي", "الاي دي", "معرفي", "/id", "/myid"]:
            bot.reply_to(message, f"🆔 <b>معرفك الشخصي (Telegram ID) هو:</b> <code>{message.chat.id}</code>\n\nانسخه وضعه داخل ملف <b>.env</b> في متغير <b>SUPER_ADMIN_ID</b> لتفعيل صلاحيات الإدارة الكاملة لك!")
            return
        elif text_lower in ["بدء", "start", "/start", "القائمة", "المول", "مرحبا", "سلام", "قائمة"]:
            clear_user_state(chat_id)
            send_mall_menu(chat_id)
            return

        # معالجة خطوات الشراء للزبون
        if state == "checkout_name" and message.text:
            extra_data["customer_name"] = message.text.strip()
            set_user_state(chat_id, "checkout_phone", store_id, extra_data)
            bot.send_message(chat_id, "📱 <b>[2/3] أرسل رقم هاتفك الآن</b> ليتمكن مندوب التوصيل أو الدعم من التواصل معك:")

        elif state == "checkout_phone" and message.text:
            extra_data["customer_phone"] = message.text.strip()
            order_type = extra_data.get("order_type", "")
            if order_type and "صالة" in order_type:
                # إذا كان الطلب صالة (طاولة)، نتمم الطلب مباشرة دون الحاجة لعنوان التوصيل
                finalize_order(chat_id, store_id, extra_data, address_text=order_type)
            else:
                set_user_state(chat_id, "checkout_address", store_id, extra_data)
                bot.send_message(
                    chat_id,
                    "📍 <b>[3/3] أرسل عنوان توصيلك بالتفصيل الآن</b> (أو أرسل موقعك الجغرافي 📍 عبر التليجرام):"
                )

        elif state == "checkout_address":
            address_text = message.text.strip() if message.text else "موقع جغرافي مشارك (GPS)"
            if message.location:
                address_text = f"📍 موقع GPS: https://maps.google.com/?q={message.location.latitude},{message.location.longitude}"
            send_payment_selection(chat_id, store_id, extra_data, address_text)

        elif state == "waiting_receipt":
            if message.photo:
                photo_id = message.photo[-1].file_id
                extra_data["receipt_photo"] = photo_id
                address_text = extra_data.get("address", "غير محدد")
                bot.send_message(chat_id, "✅ تم استلام صورة إيصال الدفع بنجاح وجاري إرسال الطلب للإدارة...")
                finalize_order(chat_id, store_id, extra_data, address_text)
            else:
                bot.send_message(chat_id, "❌ يرجى إرسال **صورة (سكرين شوت)** لوصل التحويل المالي لإنهاء الطلب، أو أرسل /cancel للعودة.")

        # خطوات إضافة وتعديل الأقسام والمنتجات والمتاجر للإدمن
        elif text_lower in ["/cancel", "إلغاء", "الغاء", "cancel"]:
            clear_user_state(chat_id)
            bot.send_message(chat_id, "✅ تم إلغاء العملية والعودة للقائمة الرئيسية.", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("👑 لوحة التحكم", callback_data="admin_main")))

        elif state == "waiting_cat_add" and message.text and is_store_admin(chat_id, store_id):
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            cat_id = f"cat_{uuid.uuid4().hex[:6]}"
            if "categories" not in store:
                store["categories"] = {}
            store["categories"][cat_id] = message.text.strip()
            save_db(db)
            clear_user_state(chat_id)
            bot.send_message(chat_id, f"✅ تم إدراج القسم الجديد «{message.text.strip()}» بنجاح في متجرك!", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))

        elif state == "waiting_cat_rename" and message.text and is_store_admin(chat_id, store_id):
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            cat_id = extra_data.get("category_id")
            if cat_id and cat_id in store.get("categories", {}):
                store["categories"][cat_id] = message.text.strip()
                save_db(db)
                bot.send_message(chat_id, f"✅ تم تغيير اسم القسم بنجاح إلى: {message.text.strip()}", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))
            clear_user_state(chat_id)

        elif state == "waiting_prod_name" and message.text and is_store_admin(chat_id, store_id):
            extra_data["name"] = message.text.strip()
            set_user_state(chat_id, "waiting_prod_price", store_id, extra_data)
            bot.send_message(chat_id, "💰 أرسل الآن <b>سعر المنتج بالدينار العراقي</b> (أرقام فقط، مثلاً: 7500 أو 12000):\n\n*(أو أرسل /cancel للإلغاء)*")

        elif state == "waiting_prod_price" and message.text and is_store_admin(chat_id, store_id):
            try:
                price = float(message.text.strip())
                extra_data["price"] = price
                set_user_state(chat_id, "waiting_prod_desc", store_id, extra_data)
                bot.send_message(chat_id, "📝 أرسل الآن <b>وصف وتفاصيل المنتج</b>:\n\n*(أو أرسل /cancel للإلغاء)*")
            except ValueError:
                bot.send_message(chat_id, "❌ يرجى إرسال رقم السعر بشكل صحيح بالدينار العراقي (أرقام فقط، مثلاً: 5000 أو 15000):")

        elif state == "waiting_prod_desc" and message.text and is_store_admin(chat_id, store_id):
            extra_data["desc"] = message.text.strip()
            set_user_state(chat_id, "waiting_prod_image", store_id, extra_data)
            bot.send_message(chat_id, "🖼️ أرسل الآن <b>صورة المنتج</b> (أرسل الصورة مباشرة من هاتفك أو رابط لها على الإنترنت)، أو أرسل <b>0</b> لتخطي إضافة الصورة وحفظ المنتج الآن:")

        elif state == "waiting_prod_image" and is_store_admin(chat_id, store_id):
            img_val = ""
            if message.photo:
                img_val = message.photo[-1].file_id
            elif message.text:
                txt = message.text.strip()
                if txt not in ["0", "تخطي", "/skip", "skip", "لا"]:
                    img_val = txt

            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            prod_id = f"prod_{uuid.uuid4().hex[:6]}"
            if "products" not in store:
                store["products"] = {}
            store["products"][prod_id] = {
                "id": prod_id,
                "category_id": extra_data["category_id"],
                "name": extra_data["name"],
                "price": extra_data["price"],
                "desc": extra_data["desc"],
                "image": img_val
            }
            save_db(db)
            clear_user_state(chat_id)
            bot.send_message(chat_id, f"✅ تم إضافة المنتج «{extra_data['name']}» بسعر {format_price(extra_data['price'])} إلى المتجر بنجاح!", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))

        elif state == "waiting_prod_reimg" and is_store_admin(chat_id, store_id):
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            prod_id = extra_data.get("prod_id")
            if prod_id and prod_id in store.get("products", {}):
                img_val = ""
                if message.photo:
                    img_val = message.photo[-1].file_id
                elif message.text:
                    txt = message.text.strip()
                    if txt not in ["0", "حذف", "إزالة", "/delete", "delete"]:
                        img_val = txt
                store["products"][prod_id]["image"] = img_val
                save_db(db)
                status_msg = "✅ تم تعيين الصورة الجديدة للمنتج بنجاح!" if img_val else "✅ تم إزالة الصورة من المنتج بنجاح!"
                bot.send_message(chat_id, status_msg, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 العودة لإدارة المتجر", callback_data=f"admin_store|{store_id}")))
            clear_user_state(chat_id)

        elif state == "waiting_prod_rename" and message.text and is_store_admin(chat_id, store_id):
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            prod_id = extra_data.get("prod_id")
            if prod_id and prod_id in store.get("products", {}):
                store["products"][prod_id]["name"] = message.text.strip()
                save_db(db)
                bot.send_message(chat_id, f"✅ تم تغيير اسم المنتج إلى: {message.text.strip()}", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))
            clear_user_state(chat_id)

        elif state == "waiting_prod_reprice" and message.text and is_store_admin(chat_id, store_id):
            try:
                price = float(message.text.strip())
                db = load_db()
                store = db.get("stores", {}).get(store_id, {})
                prod_id = extra_data.get("prod_id")
                if prod_id and prod_id in store.get("products", {}):
                    store["products"][prod_id]["price"] = price
                    save_db(db)
                    bot.send_message(chat_id, f"✅ تم تغيير سعر المنتج إلى: {format_price(price)}", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))
                clear_user_state(chat_id)
            except ValueError:
                bot.send_message(chat_id, "❌ يرجى إرسال أرقام فقط للسعر بالدينار العراقي:")

        elif state == "waiting_prod_redisc" and message.text and is_store_admin(chat_id, store_id):
            try:
                old_price = float(message.text.strip())
                if old_price < 0:
                    old_price = 0
                db = load_db()
                store = db.get("stores", {}).get(store_id, {})
                prod_id = extra_data.get("prod_id")
                if prod_id and prod_id in store.get("products", {}):
                    store["products"][prod_id]["old_price"] = old_price
                    save_db(db)
                    msg_txt = f"✅ تم تحديد السعر القديم (التخفيض) بنجاح: {format_price(old_price)}" if old_price > 0 else "✅ تم إلغاء التخفيض بنجاح."
                    bot.send_message(chat_id, msg_txt, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))
                clear_user_state(chat_id)
            except ValueError:
                bot.send_message(chat_id, "❌ يرجى إرسال أرقام فقط للسعر بالدينار العراقي:")

        elif state == "waiting_prod_redesc" and message.text and is_store_admin(chat_id, store_id):
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            prod_id = extra_data.get("prod_id")
            if prod_id and prod_id in store.get("products", {}):
                store["products"][prod_id]["desc"] = message.text.strip()
                save_db(db)
                bot.send_message(chat_id, f"✅ تم تغيير وصف المنتج بنجاح!", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))
            clear_user_state(chat_id)

        elif state == "waiting_store_name" and message.text and is_store_admin(chat_id, store_id):
            db = load_db()
            if store_id in db.get("stores", {}):
                db["stores"][store_id]["name"] = message.text.strip()
                save_db(db)
                bot.send_message(chat_id, f"✅ تم تغيير اسم المتجر بنجاح إلى: {message.text.strip()}", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))
            clear_user_state(chat_id)

        elif state == "waiting_store_desc" and message.text and is_store_admin(chat_id, store_id):
            db = load_db()
            if store_id in db.get("stores", {}):
                db["stores"][store_id]["desc"] = message.text.strip()
                save_db(db)
                bot.send_message(chat_id, f"✅ تم تغيير وصف المتجر بنجاح!", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))
            clear_user_state(chat_id)

        elif state == "waiting_delivery_fee" and message.text and is_store_admin(chat_id, store_id):
            try:
                fee = float(message.text.strip())
                if fee < 0:
                    fee = 0
                db = load_db()
                if store_id in db.get("stores", {}):
                    db["stores"][store_id]["delivery_fee"] = fee
                    db["stores"][store_id]["delivery_mode"] = "paid" if fee > 0 else "free"
                    save_db(db)
                    bot.send_message(chat_id, f"✅ تم تحديد أجور التوصيل بنجاح: {format_price(fee)}", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 إعدادات المتجر", callback_data=f"admin_settings|{store_id}")))
                clear_user_state(chat_id)
            except ValueError:
                bot.send_message(chat_id, "❌ يرجى إرسال رقم صحيح لأجور التوصيل بالدينار العراقي (أو 0 للمجاني):")

        elif state == "waiting_wallet_number" and message.text and is_store_admin(chat_id, store_id):
            db = load_db()
            if store_id in db.get("stores", {}):
                db["stores"][store_id]["wallet_number"] = message.text.strip()
                save_db(db)
                bot.send_message(chat_id, f"✅ تم حفظ رقم محفظة زين كاش بنجاح:\n<code>{message.text.strip()}</code>", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 إعدادات المتجر", callback_data=f"admin_settings|{store_id}")))
            clear_user_state(chat_id)

        elif state == "waiting_store_admin" and message.text and is_super_admin(chat_id):
            db = load_db()
            if store_id in db.get("stores", {}):
                new_admin = message.text.strip()
                if new_admin == "0":
                    db["stores"][store_id]["admin_id"] = ""
                    bot.send_message(chat_id, "✅ تم إزالة مدير المتجر، وأصبح خاضعاً للإدمن العام فقط.", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))
                else:
                    db["stores"][store_id]["admin_id"] = new_admin
                    bot.send_message(chat_id, f"✅ تم تعيين الـ Telegram ID «{new_admin}» كمدير لهذا المتجر بنجاح!", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))
                save_db(db)
            clear_user_state(chat_id)

        elif state == "waiting_clone_name" and message.text and is_super_admin(chat_id):
            db = load_db()
            orig_store = db.get("stores", {}).get(store_id, {})
            if orig_store:
                new_id = f"store_{uuid.uuid4().hex[:6]}"
                new_store = copy.deepcopy(orig_store)
                new_store["id"] = new_id
                new_store["name"] = message.text.strip()
                new_store["admin_id"] = ""
                # تحديث معرفات الأقسام والمنتجات لضمان استقلال مطلق 100%
                old_to_new_cats = {}
                new_cats = {}
                for old_cid, c_name in new_store.get("categories", {}).items():
                    new_cid = f"cat_{uuid.uuid4().hex[:6]}"
                    old_to_new_cats[old_cid] = new_cid
                    new_cats[new_cid] = c_name
                new_store["categories"] = new_cats

                new_prods = {}
                for old_pid, p_data in new_store.get("products", {}).items():
                    new_pid = f"prod_{uuid.uuid4().hex[:6]}"
                    p_data["id"] = new_pid
                    old_cid = p_data.get("category_id")
                    if old_cid in old_to_new_cats:
                        p_data["category_id"] = old_to_new_cats[old_cid]
                    new_prods[new_pid] = p_data
                new_store["products"] = new_prods

                db["stores"][new_id] = new_store
                save_db(db)
                clear_user_state(chat_id)

                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("👤 تعيين رقم جوال المشتري (admin_id) على هذا المتجر المستنسخ", callback_data=f"aset_admin|{new_id}"),
                    types.InlineKeyboardButton(f"🛠️ الدخول لإدارة {new_store['name']}", callback_data=f"admin_store|{new_id}")
                )
                bot.send_message(chat_id, f"🎉 <b>تم استلام واستنساخ المتجر بنجاح!</b>\n🏬 الاسم الجديد: <b>{new_store['name']}</b>\n━━━━━━━━━━━━━━━━━━\n✅ تم نسخ <b>({len(new_cats)}) أقسام</b> و <b>({len(new_prods)}) أصناف</b> كنسخة مستقلة 100% لا تؤثر أبداً على المتجر الأصلي أو أي متجر آخر.\n\n👇 يمكنك الآن مباشرة تعيين رقم جوال التليجرام الخاص بالمشتري ليتسلم المتجر:", reply_markup=markup)
            else:
                clear_user_state(chat_id)

        elif state == "waiting_new_store_name" and message.text and is_super_admin(chat_id):
            new_store_id = f"store_{uuid.uuid4().hex[:6]}"
            set_user_state(chat_id, "waiting_new_store_desc", new_store_id, {"name": message.text.strip()})
            bot.send_message(chat_id, "💬 أرسل الآن <b>وصف هذا المتجر الجديد</b>:\n\n*(أو أرسل /cancel للإلغاء)*")

        elif state == "waiting_new_store_desc" and message.text and is_super_admin(chat_id):
            db = load_db()
            if "stores" not in db:
                db["stores"] = {}
            store_name = extra_data.get("name", "متجر جديد")
            db["stores"][store_id] = {
                "id": store_id,
                "name": store_name,
                "desc": message.text.strip(),
                "admin_id": "",
                "categories": {},
                "products": {},
                "hidden": False,
                "sector": "shopping"
            }
            save_db(db)
            clear_user_state(chat_id)
            bot.send_message(chat_id, f"🎉 تم إنشاء المتجر الجديد «{store_name}» وإضافته للمجمع التجاري بنجاح!", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⚙️ إدارة المتجر الجديد", callback_data=f"admin_store|{store_id}")))

        else:
            send_mall_menu(chat_id)

from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "🔥 Multi-Store Mall Bot is LIVE and Running 24/7 on Render! 🚀"

if __name__ == "__main__":
    if bot:
        print("==================================================")
        print("🔥 Multi-Store Mall Bot is LIVE and Running... 🚀")
        print("==================================================")
        try:
            threading.Thread(target=promo_scheduler_loop, daemon=True).start()
            print("📢 [Promo Scheduler] Background broadcast thread started successfully.")
            
            def run_bot_polling():
                bot.infinity_polling(timeout=20, long_polling_timeout=20)
                
            threading.Thread(target=run_bot_polling, daemon=True).start()
            print("🤖 [Telegram Bot] Polling thread started successfully.")
            
            port = int(os.environ.get("PORT", 10000))
            app.run(host="0.0.0.0", port=port)
        except Exception as err:
            print(f"[Startup Error]: {err}")
    else:
        print("[ERROR] لم يتم بدء البوت لعدم وجود توكن صحيح.")
