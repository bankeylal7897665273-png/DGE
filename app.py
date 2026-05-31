import telebot
from flask import Flask, request, render_template_string
import requests
import time
import uuid
import re
import os
import logging
from config import BOT_TOKEN, FIREBASE_URL

# Threading ko False rakha hai taaki Render par bot crash na ho
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
telebot.logger.setLevel(logging.INFO)

app = Flask(__name__)

# Firebase Helper Functions
def fb_get(path):
    try:
        r = requests.get(f"{FIREBASE_URL}{path}.json", timeout=5)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def fb_put(path, data):
    try:
        r = requests.put(f"{FIREBASE_URL}{path}.json", json=data, timeout=5)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def fb_patch(path, data):
    try:
        r = requests.patch(f"{FIREBASE_URL}{path}.json", json=data, timeout=5)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def fb_delete(path):
    try:
        requests.delete(f"{FIREBASE_URL}{path}.json", timeout=5)
    except:
        pass

# Advanced Indian SIM Card Detection Logic
def detect_sim(number):
    # Number se saare extra spaces ya characters hatayein
    num = re.sub(r'\D', '', number)
    if len(num) > 10:
        num = num[-10:] # Agar +91 lagaya ho toh last 10 digits lein
        
    if len(num) == 10:
        # Major Indian Telecom Series database match
        jio_series = ('600', '700', '701', '702', '790', '808', '809', '887', '901', '910', '920', '932', '933', '938', '996', '788')
        airtel_series = ('981', '984', '989', '991', '993', '998', '999', '801', '813', '888', '889', '704', '707', '763', '956', '971')
        
        if num.startswith(jio_series):
            return "JIO"
        elif num.startswith(airtel_series):
            return "AIRTEL"
        else:
            # Fallback rules based on starting digits
            if num[0] in ('6', '7'):
                return "JIO"
            elif num[0] in ('8', '9'):
                return "AIRTEL"
    return "UNKNOWN SIM"

# --- TELEGRAM BOT LOGIC ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        chat_id = str(message.chat.id)
        first_name = message.from_user.first_name or "User"
        
        fb_patch(f"/users/{chat_id}", {"name": first_name})
        fb_patch(f"/states/{chat_id}", {"step": "start"})
        
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(
            telebot.types.InlineKeyboardButton("🎁 FREE DATA", callback_data="free_data"),
            telebot.types.InlineKeyboardButton("💳 PAID BY DATA", callback_data="paid_data")
        )
        bot.send_message(chat_id, "<b>🎉 Welcome to Data Pack Giveaway Bot!</b>\n\nPlease select an option below:", reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        print(f"Error in start command: {e}")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    try:
        chat_id = str(message.chat.id)
        text = message.text.strip()
        
        state = fb_get(f"/states/{chat_id}")
        if not state:
            state = {"step": "start"}
        
        step = state.get("step", "start")

        if step == 'awaiting_key':
            pack_id = state.get('pack_id')
            user_key = text
            
            key_data = fb_get(f"/keys/{user_key}")
            
            if key_data and key_data.get('pack_id') == pack_id:
                current_time = int(time.time())
                uses = int(key_data.get('uses', 0))
                
                # Check Time Limit and Use Count strictly
                if current_time <= key_data.get('expiry_time', 0) and uses > 0:
                    
                    # FIX: Key ko turant update/burn karo taaki koi dusra use na kar sake
                    new_uses = uses - 1
                    if new_uses <= 0:
                        fb_delete(f"/keys/{user_key}")
                    else:
                        fb_patch(f"/keys/{user_key}", {"uses": new_uses})
                    
                    fb_patch(f"/states/{chat_id}", {"step": "awaiting_number", "key_used": user_key})
                    bot.send_message(chat_id, "✅ <b>Key Verified Successfully!</b>\n\nPlease enter your Mobile Number (10 digits):", parse_mode="HTML")
                else:
                    bot.send_message(chat_id, "❌ <b>Expired Key!</b>\nTime limit crossed or this key has reached its maximum user limit.", parse_mode="HTML")
                    fb_patch(f"/states/{chat_id}", {"step": "start"})
            else:
                bot.send_message(chat_id, "❌ <b>Wrong Key!</b> Please enter correct key for this pack.", parse_mode="HTML")
            return

        if step == 'awaiting_number':
            number = text
            # Agar number validate hota hai
            if len(re.sub(r'\D', '', number)) >= 10:
                sim_name = detect_sim(number)
                
                fb_patch(f"/states/{chat_id}", {
                    "step": "ready_submit",
                    "number": number,
                    "sim": sim_name
                })

                msg_text = (
                    "📱 <b>Number Auto-Detected!</b>\n\n"
                    f"📞 <b>Number:</b> {number}\n"
                    f"📡 <b>SIM Card Operator:</b> {sim_name}\n\n"
                    "Click <b>Submit</b> to send request to Admin."
                )

                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton("✅ SUBMIT REQUEST", callback_data="submit_request"))
                bot.send_message(chat_id, msg_text, reply_markup=markup, parse_mode="HTML")
            else:
                bot.send_message(chat_id, "❌ Please enter a valid 10-digit mobile number.")
            return
    except Exception as e:
        print(f"Error in text handler: {e}")

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    try:
        chat_id = str(call.message.chat.id)
        callback_data = call.data
        first_name = call.from_user.first_name or "User"

        if callback_data == 'free_data':
            packs = fb_get("/packs")
            if not packs:
                bot.send_message(chat_id, "No free packs available right now.")
                return

            for pack_id, pack in packs.items():
                price = str(pack.get('price'))
                price_text = "00PACK" if price in ['0', '00'] else f"{price} RS"
                
                msg_text = (
                    "╔═════════════════════════╗\n"
                    "╠ 🎁 <b>FREE DATA GIVEAWAY</b>\n"
                    "╠═════════════════════════╣\n"
                    f"╠ 📦 <b>Data:</b> {pack.get('data_amount')}\n"
                    f"╠ 💰 <b>Price:</b> {price_text}\n"
                    f"╠ 📜 <b>Condition:</b> {pack.get('conditions')}\n"
                    "╚═════════════════════════╝\n\n"
                    "<i>To claim this pack, click below!</i>"
                )

                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton(f"🚀 CLAIM {price_text}", callback_data=f"claim_{pack_id}"))
                bot.send_message(chat_id, msg_text, reply_markup=markup, parse_mode="HTML")
            return

        if callback_data == 'paid_data':
            bot.send_message(chat_id, "Paid data option coming soon. Only free is active right now.")
            return

        if callback_data.startswith('claim_'):
            pack_id = callback_data.replace('claim_', '')
            fb_patch(f"/states/{chat_id}", {"step": "awaiting_key", "pack_id": pack_id})
            bot.send_message(chat_id, "🔑 <b>Enter Access Key!</b>\n\nPlease send the admin-provided key for this pack. (Key has time and user limits)", parse_mode="HTML")
            return

        if callback_data == 'submit_request':
            state = fb_get(f"/states/{chat_id}")
            if state and state.get('step') == 'ready_submit':
                req_id = "req_" + str(uuid.uuid4().hex)[:8]

                request_data = {
                    "chat_id": chat_id,
                    "name": first_name,
                    "pack_id": state.get('pack_id'),
                    "number": state.get('number'),
                    "sim": state.get('sim'),
                    "status": "pending"
                }
                fb_put(f"/requests/{req_id}", request_data)
                fb_patch(f"/states/{chat_id}", {"step": "start"})

                bot.send_message(chat_id, "✅ <b>Success!</b>\nYour request has been sent to the Admin. Please wait for verification.", parse_mode="HTML")
            return
    except Exception as e:
        print(f"Error in callback: {e}")

# --- FLASK ADMIN PANEL & ROUTES ---
ADMIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Giveaway Admin Panel</title>
    <style>
        body { font-family: Arial, sans-serif; background: #111; color: #fff; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: auto; }
        .box { background: #222; padding: 20px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #9c27b0; }
        h2 { color: #e040fb; border-bottom: 1px solid #444; padding-bottom: 10px; }
        input, select, button { width: 100%; padding: 10px; margin: 5px 0 15px; border-radius: 5px; border: 1px solid #555; background: #333; color: #fff; box-sizing: border-box;}
        button { background: #9c27b0; font-weight: bold; cursor: pointer; border: none; }
        button:hover { background: #e040fb; }
        .req-card { background: #333; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
        .success-btn { background: #4caf50; width: 48%; display: inline-block; }
        .reject-btn { background: #f44336; width: 48%; display: inline-block; }
        .msg { background: #4caf50; padding: 10px; border-radius: 5px; margin-bottom: 20px; }
        .pack-item { background: #2d2d2d; padding: 10px; margin-bottom: 8px; border-radius: 5px; display: flex; justify-content: space-between; align-items: center;}
        .delete-btn { background: #d32f2f; width: auto; padding: 5px 12px; margin: 0;}
    </style>
</head>
<body>
<div class="container">
    <h1 style="text-align: center; color: #e040fb;">🚀 Admin Panel - VIP Bot</h1>
    
    {% if msg %}
    <div class='msg'>{{ msg }}</div>
    {% endif %}

    <div class="box" style="border-color: #00e676; text-align: center;">
        <h2>📊 User Management</h2>
        <p style="font-size: 22px; margin: 5px 0;">Total Bot Registered Users: <b style="color:#00e676;">{{ total_users }}</b></p>
    </div>

    <div class="box">
        <h2>1. Add Free Pack</h2>
        <form method="POST">
            <input type="text" name="pack_name" placeholder="Pack Name (e.g. Jio 3GB)" required>
            <input type="text" name="price" placeholder="Price (e.g. 00 or 3)" required>
            <input type="text" name="data_amount" placeholder="Data Amount (e.g. 1 GB)" required>
            <input type="text" name="conditions" placeholder="Condition (e.g. Subscribe channel)" required>
            <button type="submit" name="add_pack">Add Pack</button>
        </form>
    </div>

    <div class="box">
        <h2>2. Manage & Delete Packs</h2>
        {% if packs %}
            {% for pid, p in packs.items() %}
                <div class="pack-item">
                    <span>📦 <b>{{ p.name }}</b> ({{ p.data_amount }}) - {{ p.price }} RS</span>
                    <form method="POST" style="margin:0;">
                        <input type="hidden" name="pack_id" value="{{ pid }}">
                        <button type="submit" name="delete_pack" class="delete-btn">❌ Delete</button>
                    </form>
                </div>
            {% endfor %}
        {% else %}
            <p>No packs added yet.</p>
        {% endif %}
    </div>

    <div class="box">
        <h2>3. Generate Key</h2>
        <form method="POST">
            <select name="pack_id" required>
                <option value="">Select Pack...</option>
                {% if packs %}
                    {% for pid, p in packs.items() %}
                        <option value="{{ pid }}">{{ p.name }} - {{ p.data_amount }}</option>
                    {% endfor %}
                {% endif %}
            </select>
            <input type="text" name="key_string" placeholder="Enter custom Key (e.g. VIP888)" required>
            <input type="number" name="uses" placeholder="Max Users can use (e.g. 1)" required>
            <input type="number" name="expiry_mins" placeholder="Working Time limit (in minutes, e.g. 1)" required>
            <button type="submit" name="add_key">Generate Key</button>
        </form>
    </div>

    <div class="box">
        <h2>4. Free Requests</h2>
        {% if requests_data %}
            {% for rid, req in requests_data.items() %}
                <div class='req-card'>
                    <b>User Name:</b> {{ req.name }}<br>
                    <b>Number:</b> {{ req.number }}<br>
                    <b>SIM Detect:</b> <span style="color:#e040fb; font-weight:bold;">{{ req.sim }}</span><br><br>
                    <form method='POST' style='margin:0;'>
                        <input type='hidden' name='req_id' value='{{ rid }}'>
                        <input type='text' name='img_url' placeholder='Image URL (Mandatory for Success)'>
                        <input type='hidden' name='action_type' id='action_type_{{ rid }}' value=''>
                        <button type='submit' name='action_request' value='success' class='success-btn' onclick="document.getElementById('action_type_{{ rid }}').value='success'; if(this.form.img_url.value == ''){alert('Please provide Image URL'); return false;}">✅ Success</button>
                        <button type='submit' name='action_request' value='reject' class='reject-btn' onclick="document.getElementById('action_type_{{ rid }}').value='reject';">❌ Reject</button>
                    </form>
                </div>
            {% endfor %}
        {% else %}
            <p>No pending requests.</p>
        {% endif %}
    </div>
</div>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def admin_panel():
    msg = ""
    if request.method == 'POST':
        if 'add_pack' in request.form:
            pack_id = "pack_" + str(uuid.uuid4().hex)[:6]
            data = {
                'name': request.form['pack_name'],
                'data_amount': request.form['data_amount'],
                'price': request.form['price'],
                'conditions': request.form['conditions']
            }
            fb_put(f"/packs/{pack_id}", data)
            msg = "Pack Added Successfully!"
            
        elif 'delete_pack' in request.form:
            pid = request.form['pack_id']
            fb_delete(f"/packs/{pid}")
            msg = "Pack Deleted Successfully!"

        elif 'add_key' in request.form:
            key_str = request.form['key_string'].strip()
            expiry_mins = int(request.form['expiry_mins'])
            data = {
                'pack_id': request.form['pack_id'],
                'uses': int(request.form['uses']),
                'expiry_time': int(time.time()) + (expiry_mins * 60)
            }
            fb_put(f"/keys/{key_str}", data)
            msg = f"Key Generated: {key_str} (Valid for {expiry_mins} min)"

        elif 'action_request' in request.form:
            req_id = request.form['req_id']
            action = request.form['action_type']
            req_data = fb_get(f"/requests/{req_id}")
            
            if action == 'reject' and req_data:
                try:
                    bot.send_message(req_data['chat_id'], "❌ Your giveaway request was Rejected by Admin.")
                except: pass
                fb_delete(f"/requests/{req_id}")
                msg = "Request Rejected."
            
            elif action == 'success' and req_data:
                img_url = request.form['img_url']
                win_msg = "🎉 <b>Congratulations!</b> Your request was approved."
                try:
                    bot.send_photo(req_data['chat_id'], img_url, caption=win_msg, parse_mode="HTML")
                except: pass

                all_users = fb_get("/users")
                if all_users:
                    tg_name = req_data.get('name', 'User')
                    broadcast_msg = f"🏆 <b>GIVEAWAY WINNER ANNOUNCEMENT</b> 🏆\n\n👤 <b>Winner:</b> {tg_name}\n🎉 <b>Giveaway Winner!</b>\nCongratulations to them!"
                    for uid in all_users.keys():
                        try:
                            bot.send_photo(uid, img_url, caption=broadcast_msg, parse_mode="HTML")
                        except: pass
                
                fb_delete(f"/requests/{req_id}")
                msg = "Request Success & Broadcasted!"

    packs = fb_get("/packs") or {}
    requests_data = fb_get("/requests") or {}
    all_users = fb_get("/users") or {}
    total_users = len(all_users)
    
    return render_template_string(ADMIN_HTML, msg=msg, packs=packs, requests_data=requests_data, total_users=total_users)

@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    try:
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "!", 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return "!", 500

@app.route("/setwebhook")
def webhook():
    bot.remove_webhook()
    time.sleep(1)
    url = request.host_url + BOT_TOKEN
    bot.set_webhook(url=url)
    return f"✅ Webhook successfully set to: {url}", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
