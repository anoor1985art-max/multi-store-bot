import os
import sys
import json
import uuid
import time
import threading
from dotenv import load_dotenv
import telebot
from telebot import types

# إعداد ترميز الشاشة في نظام ويندوز
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SUPER_ADMIN_ID = str(os.environ.get("SUPER_ADMIN_ID", "")).strip()

if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("[WARNING] يرجى وضع توكن البوت في ملف .env داخل المتغير TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML") if TOKEN and TOKEN != "YOUR_BOT_TOKEN_HERE" else None

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.json")
db_lock = threading.Lock()

def load_db():
    with db_lock:
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Error loading DB]: {e}")
        return {"stores": {}, "orders": {}}

def save_db(data):
    with db_lock:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# هيكل ذاكرة التخزين المؤقت:
# user_states: { chat_id: {"state": "...", "store_id": "...", "data": {...}} }
# user_carts: { chat_id: { store_id: { prod_id: quantity } } }
user_states = {}
user_carts = {}

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
    return str(chat_id) == str(SUPER_ADMIN_ID)

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
# 1. واجهة المجمع التجاري (Mall Main Menu)
# ==========================================
def send_mall_menu(chat_id, message_id=None):
    db = load_db()
    stores = db.get("stores", {})
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s_id, s_info in stores.items():
        if not s_info.get("hidden", False) or is_store_admin(chat_id, s_id):
            status_badge = " 🔒 [مخفي]" if s_info.get("hidden", False) else ""
            markup.add(types.InlineKeyboardButton(f"🏬 {s_info.get('name', 'متجر')}{status_badge}", callback_data=f"open_store|{s_id}"))
    
    # تحقق مما إذا كان المستخدم مشرفاً لإظهار زر لوحة الإدارة
    is_admin_any = is_super_admin(chat_id)
    if not is_admin_any:
        for s_info in stores.values():
            if str(s_info.get("admin_id", "")).strip() == str(chat_id):
                is_admin_any = True
                break
                
    if is_admin_any:
        markup.add(types.InlineKeyboardButton("👑 لوحة تحكم الإدارة والمتاجر", callback_data="admin_main"))
    
    text = (
        "🏢 <b>أهلاً بك في المجمع التجاري الذكي متعدد المتاجر! 🛍️✨</b>\n\n"
        "إليك قائمة بالمتاجر المتاحة في مجمعنا اليوم، اضغط على المتجر الذي ترغب بالتسوق منه وتصفح أقسامه:"
    )
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
    
    markup.add(
        types.InlineKeyboardButton(f"🛒 سلة مشترياتي ({total_items})", callback_data=f"view_cart|{store_id}"),
        types.InlineKeyboardButton("🔙 العودة لقائمة المتاجر", callback_data="mall_home")
    )

    if is_store_admin(chat_id, store_id):
        markup.add(types.InlineKeyboardButton("⚙️ إدارة هذا المتجر (لوحة الإدمن)", callback_data=f"admin_store|{store_id}"))

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

def send_category_products(chat_id, store_id, cat_id, message_id=None):
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    cat_name = store.get("categories", {}).get(cat_id, "قسم غير معروف")
    
    products = [p for p in store.get("products", {}).values() if p.get("category_id") == cat_id]
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    if not products:
        text = f"📁 <b>{cat_name}</b>\n\n❌ <i>لا توجد منتجات حالياً داخل هذا القسم، يرجى تصفحه لاحقاً.</i>"
    else:
        text = f"📁 <b>{cat_name}</b>\n\n👇 <i>اختر المنتج لعرض تفاصيله وسعره وإضافته للسلة:</i>"
        for p in products:
            markup.add(types.InlineKeyboardButton(f"🔹 {p['name']} - ({p['price']}$)", callback_data=f"view_prod|{store_id}|{p['id']}"))
    
    markup.add(
        types.InlineKeyboardButton("🛒 سلة المشتريات", callback_data=f"view_cart|{store_id}"),
        types.InlineKeyboardButton("🔙 العودة لأقسام المتجر", callback_data=f"open_store|{store_id}")
    )

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

def send_product_card(chat_id, store_id, prod_id, message_id=None):
    db = load_db()
    store = db.get("stores", {}).get(store_id, {})
    prod = store.get("products", {}).get(prod_id)
    if not prod:
        bot.send_message(chat_id, "❌ المنتج لم يعد متوفراً.")
        return

    cart = get_user_cart(chat_id, store_id)
    qty = cart.get(prod_id, 0)

    caption = (
        f"🏷️ <b>{prod['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>السعر:</b> <code>{prod['price']}$</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>الوصف والتفاصيل:</b>\n<i>{prod['desc']}</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🛒 <b>الكمية حالياً في سلتك:</b> ({qty})\n"
    )

    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("➖", callback_data=f"dec_cart|{store_id}|{prod_id}"),
        types.InlineKeyboardButton(f"🛒 الكمية ({qty})", callback_data=f"view_cart|{store_id}"),
        types.InlineKeyboardButton("➕ إضافة", callback_data=f"inc_cart|{store_id}|{prod_id}")
    )
    markup.add(types.InlineKeyboardButton("🔙 العودة للقسم", callback_data=f"open_cat|{store_id}|{prod['category_id']}"))

    img_url = prod.get("image", "").strip()
    if img_url and img_url.startswith("http"):
        if message_id:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
        bot.send_photo(chat_id, img_url, caption=caption, reply_markup=markup)
    else:
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
                text += f"🔹 <b>{prod['name']}</b>\n     الكمية: {qty} × {prod['price']}$ = <code>{subtotal}$</code>\n"
                markup.add(
                    types.InlineKeyboardButton("➖", callback_data=f"dec_cart|{store_id}|{p_id}"),
                    types.InlineKeyboardButton(f"{prod['name'][:15]} ({qty})", callback_data=f"view_prod|{store_id}|{p_id}"),
                    types.InlineKeyboardButton("➕", callback_data=f"inc_cart|{store_id}|{p_id}")
                )
        text += f"━━━━━━━━━━━━━━━━━━\n💰 <b>المبلغ الإجمالي المنسوب: <code>{total}$</code></b>\n\n👇 اضغط على زر إتمام الطلب لتعبئة بيانات التوصيل والدفع:"
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

def start_checkout_flow(chat_id, store_id, message_id=None):
    set_user_state(chat_id, "checkout_name", store_id, {})
    text = (
        "📝 <b>خطوات إتمام الطلب والتوصيل [1/3]</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "👤 يرجى إرسال <b>اسمك الكامل</b> الآن في رسالة لنعتمده في الفاتورة والتوصيل:"
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text)

# ==========================================
# 4. لوحة الإدارة الشاملة (Multi-Admin Panel)
# ==========================================
def send_admin_main(chat_id, message_id=None):
    db = load_db()
    stores = db.get("stores", {})
    markup = types.InlineKeyboardMarkup(row_width=1)

    if is_super_admin(chat_id):
        for s_id, s_info in stores.items():
            markup.add(types.InlineKeyboardButton(f"🛠️ إدارة: {s_info['name']}", callback_data=f"admin_store|{s_id}"))
        markup.add(types.InlineKeyboardButton("➕ إنشاء متجر جديد في المجمع", callback_data="admin_add_store"))
    else:
        for s_id, s_info in stores.items():
            if str(s_info.get("admin_id", "")).strip() == str(chat_id):
                markup.add(types.InlineKeyboardButton(f"🛠️ إدارة متجري: {s_info['name']}", callback_data=f"admin_store|{s_id}"))

    markup.add(types.InlineKeyboardButton("🔙 العودة للمول الرئيسي", callback_data="mall_home"))

    text = "👑 <b>لوحة تحكم الإدارة والمتاجر</b>\n\nاختر المتجر الذي ترغب بإدارة أقسامه ومنتجاته وطلباته:"
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
    markup.add(
        types.InlineKeyboardButton("📂 إدارة الأقسام", callback_data=f"admin_cats|{store_id}"),
        types.InlineKeyboardButton("📦 إدارة المنتجات", callback_data=f"admin_prods|{store_id}")
    )
    markup.add(
        types.InlineKeyboardButton("📊 إحصائيات وطلبات", callback_data=f"admin_stats|{store_id}"),
        types.InlineKeyboardButton("⚙️ إعدادات المتجر", callback_data=f"admin_settings|{store_id}")
    )
    hide_btn_text = "🟢 إظهار المتجر للزبائن" if store.get("hidden", False) else "👁️ إخفاء المتجر عن الزبائن"
    markup.add(types.InlineKeyboardButton(hide_btn_text, callback_data=f"toggle_hide|{store_id}"))
    markup.add(
        types.InlineKeyboardButton("🔙 العودة لقائمة المتاجر", callback_data="admin_main"),
        types.InlineKeyboardButton("🏠 دخول المتجر كزبون", callback_data=f"open_store|{store_id}")
    )

    text = (
        f"🛠️ <b>لوحة إدارة: {store.get('name', 'المتجر')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 عدد الأقسام الحالية: {len(store.get('categories', {}))}\n"
        f"📦 عدد المنتجات الحالية: {len(store.get('products', {}))}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 اختر إجراء الإدارة المطلوب من الأزرار أدناه:"
    )

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

# ==========================================
# معالجة الأزرار التفاعلية (Callback Query Handler)
# ==========================================
if bot:
    @bot.callback_query_handler(func=lambda call: True)
    def handle_callbacks(call):
        chat_id = call.message.chat.id
        data = call.data
        msg_id = call.message.message_id

        if data == "mall_home":
            clear_user_state(chat_id)
            send_mall_menu(chat_id, msg_id)

        elif data.startswith("open_store|"):
            store_id = data.split("|")[1]
            clear_user_state(chat_id)
            send_store_home(chat_id, store_id, msg_id)

        elif data.startswith("open_cat|"):
            _, store_id, cat_id = data.split("|")
            send_category_products(chat_id, store_id, cat_id, msg_id)

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
            start_checkout_flow(chat_id, store_id, msg_id)

        # أوامر الإدارة
        elif data == "admin_main":
            send_admin_main(chat_id, msg_id)

        elif data.startswith("admin_store|"):
            store_id = data.split("|")[1]
            send_admin_store_panel(chat_id, store_id, msg_id)

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
                markup.add(types.InlineKeyboardButton(f"📦 {p_info['name']} - ({p_info['price']}$)", callback_data=f"aprod_edit|{store_id}|{p_id}"))
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
            bot.send_message(chat_id, "✏️ أرسل الآن <b>اسم المنتج</b> الذي ترغب بإضافته:")

        elif data.startswith("admin_stats|"):
            store_id = data.split("|")[1]
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            orders = [o for o in db.get("orders", {}).values() if o.get("store_id") == store_id]
            total_rev = sum(o.get("total", 0) for o in orders if o.get("status") == "delivered")
            text = (
                f"📊 <b>إحصائيات المبيعات: {store.get('name')}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📦 إجمالي الطلبات المستلمة: {len(orders)}\n"
                f"💰 إجمالي الإيرادات المحققة: <code>{total_rev}$</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 العودة لإدارة المتجر", callback_data=f"admin_store|{store_id}"))
            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=markup)

    @bot.message_handler(commands=['start', 'mall'])
    def handle_start(message):
        chat_id = message.chat.id
        clear_user_state(chat_id)
        send_mall_menu(chat_id)

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

        # معالجة خطوات الشراء للزبون
        if state == "checkout_name" and message.text:
            extra_data["customer_name"] = message.text.strip()
            set_user_state(chat_id, "checkout_phone", store_id, extra_data)
            bot.send_message(chat_id, "📱 <b>[2/3] أرسل رقم هاتفك الآن</b> ليتمكن مندوب التوصيل أو الدعم من التواصل معك:")

        elif state == "checkout_phone" and message.text:
            extra_data["customer_phone"] = message.text.strip()
            set_user_state(chat_id, "checkout_address", store_id, extra_data)
            bot.send_message(
                chat_id,
                "📍 <b>[3/3] أرسل عنوان توصيلك بالتفصيل الآن</b> (أو أرسل موقعك الجغرافي 📍 عبر التليجرام):"
            )

        elif state == "checkout_address":
            address_text = message.text.strip() if message.text else "موقع جغرافي مشارك (GPS)"
            if message.location:
                address_text = f"📍 موقع GPS: https://maps.google.com/?q={message.location.latitude},{message.location.longitude}"
            
            cart = get_user_cart(chat_id, store_id)
            db = load_db()
            store = db.get("stores", {}).get(store_id, {})
            total = sum(store["products"][pid]["price"] * qty for pid, qty in cart.items() if pid in store.get("products", {}))

            order_id = uuid.uuid4().hex[:8]
            order_data = {
                "id": order_id,
                "store_id": store_id,
                "chat_id": chat_id,
                "customer_name": extra_data.get("customer_name"),
                "customer_phone": extra_data.get("customer_phone"),
                "address": address_text,
                "items": cart,
                "total": total,
                "status": "pending",
                "time": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            db["orders"][order_id] = order_data
            save_db(db)

            # تفريغ السلة وإرسال تأكيد للزبون
            user_carts[chat_id][store_id] = {}
            clear_user_state(chat_id)

            bot.send_message(
                chat_id,
                f"🎉 <b>تم استلام طلبك بنجاح! رقم الطلب: <code>#{order_id}</code></b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👤 الاسم: {order_data['customer_name']}\n"
                f"📱 الهاتف: {order_data['customer_phone']}\n"
                f"📍 العنوان: {order_data['address']}\n"
                f"💰 الإجمالي المطلُوب: <code>{total}$</code>\n\n"
                f"⏳ <i>سيقوم فريق متجر «{store.get('name', '')}» بمراجعة طلبك وتجهيزه والتواصل معك قريباً!</i>",
                reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 العودة للمول الرئيسي", callback_data="mall_home"))
            )

            # إرسال إشعار فوري لمدير المتجر
            admin_id = store.get("admin_id") or SUPER_ADMIN_ID
            if admin_id:
                try:
                    admin_text = (
                        f"🔔 <b>طلب شراء جديد في متجرك! (#{order_id})</b>\n"
                        f"🏬 المتجر: {store.get('name')}\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"👤 المستلم: {order_data['customer_name']}\n"
                        f"📱 الهاتف: <code>{order_data['customer_phone']}</code>\n"
                        f"📍 العنوان: {order_data['address']}\n"
                        f"━━━━━━━━━━━━━━━━━━\n<b>📦 تفاصيل المنتجات المطلوبة:</b>\n"
                    )
                    for pid, qty in cart.items():
                        prod = store.get("products", {}).get(pid)
                        if prod:
                            admin_text += f"▪️ {prod['name']} × ({qty}) = <code>{prod['price'] * qty}$</code>\n"
                    admin_text += f"━━━━━━━━━━━━━━━━━━\n💰 <b>إجمالي الفاتورة: <code>{total}$</code></b>"
                    bot.send_message(admin_id, admin_text)
                except Exception as e:
                    print(f"[Error notifying admin]: {e}")

        # خطوات إضافة أقسام ومنتجات للإدمن
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

        elif state == "waiting_prod_name" and message.text and is_store_admin(chat_id, store_id):
            extra_data["name"] = message.text.strip()
            set_user_state(chat_id, "waiting_prod_price", store_id, extra_data)
            bot.send_message(chat_id, "💰 أرسل الآن <b>سعر المنتج</b> (أرقام فقط، مثلاً: 45 أو 12.5):")

        elif state == "waiting_prod_price" and message.text and is_store_admin(chat_id, store_id):
            try:
                price = float(message.text.strip())
                extra_data["price"] = price
                set_user_state(chat_id, "waiting_prod_desc", store_id, extra_data)
                bot.send_message(chat_id, "📝 أرسل الآن <b>وصف وتفاصيل المنتج</b>:")
            except ValueError:
                bot.send_message(chat_id, "❌ يرجى إرسال رقم السعر بشكل صحيح (مثلاً: 25 أو 15.5):")

        elif state == "waiting_prod_desc" and message.text and is_store_admin(chat_id, store_id):
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
                "desc": message.text.strip(),
                "image": ""
            }
            save_db(db)
            clear_user_state(chat_id)
            bot.send_message(chat_id, f"✅ تم إضافة المنتج «{extra_data['name']}» بسعر {extra_data['price']}$ إلى المتجر بنجاح!", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 لوحة المتجر", callback_data=f"admin_store|{store_id}")))

if __name__ == "__main__":
    if bot:
        print("==================================================")
        print("🔥 Multi-Store Mall Bot is LIVE and Running... 🚀")
        print("==================================================")
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as err:
            print(f"[Polling Error]: {err}")
    else:
        print("[ERROR] لم يتم بدء البوت لعدم وجود توكن صحيح.")
