import telebot
from flask import Flask, request, render_template_string
import requests
import time
import uuid
import re
import os
import logging
from config import BOT_TOKEN, FIREBASE_URL

# Fix 1: Threading ko False kiya taaki Render Gunicorn ke saath bot hang na ho
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
telebot.logger.setLevel(logging.INFO)

app = Flask(__name__)

# Fix 2: Firebase me timeout lagaya taaki network slow hone par bot na ruke
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

def detect_sim(number):
    if re.match(r'^(6|7|8|9)', number):
        if re.match(r'^(70|79|88|99|62|63|89|91)', number): return "JIO"
        if re.match(r'^(98|97|96|80|81|82|83|73)', number): return "AIRTEL"
        return "JIO/AIRTEL"
    return "UNKNOWN"

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
        print(f"Error in start: {e}")

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
                if current_time <= key_data.get('expiry_time', 0) and int(key_data.get('uses', 0)) > 0:
                    fb_patch(f"/states/{chat_id}", {"step": "awaiting_number", "key_used": user_key})
                    bot.send_message(chat_id, "✅ <b>Key Verified!</b>\n\nPlease enter your Mobile Number (10 digits):", parse_mode="HTML")
                else:
                    bot.send_message(chat_id, "❌ <b>Invalid or Expired Key!</b>\nTime limit crossed or key already used.", parse_mode="HTML")
                    fb_patch(f"/states/{chat_id}", {"step": "start"})
            else:
                bot.send_message(chat_id, "❌ <b>Wrong Key!</b> Please enter correct key for this pack.", parse_mode="HTML")
            return

        if step == 'awaiting_number':
            number = text
            if len(number) >= 10:
                sim_name = detect_sim(number)
                
                fb_patch(f"/states/{chat_id}", {
                    "step": "ready_submit",
                    "number": number,
                    "sim": sim_name
                })

                msg_text = (
                    "📱 <b>Number Auto-Detected!</b>\n\n"
                    f"📞 <b>Number:</b> {number}\n"
                    f"📡 <b>SIM Card:</b> {sim_name}\n\n"
                    "Click <b>Submit</b> to send request to Admin."
                )

                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton("✅ SUBMIT REQUEST", callback_data="submit_request"))
                bot.send_message(chat_id, msg_text, reply_markup=markup, parse_mode="HTML")
            else:
                bot.send_message(chat_id, "❌ Please enter a valid 10-digit number.")
            return
    except Exception as e:
        print(f"Error in text handle: {e}")

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
                
                key_id = state.get('key_used')
                key_data = fb_get(f"/keys/{key_id}")
                if key_data:
                    new_uses = int(key_data.get('uses', 1)) - 1
                    fb_patch(f"/keys/{key_id}", {"uses": new_uses})

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
    </style>
</head>
<body>
<div class="container">
    <h1 style="text-align: center; color: #e040fb;">🚀 Admin Panel - VIP Bot</h1>
    {% if msg %}
    <div class='msg'>{{ msg }}</div>
    {% endif %}

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
        <h2>2. Generate Key</h2>
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
        <h2>3. Free Requests</h2>
        {% if requests_data %}
            {% for rid, req in requests_data.items() %}
                <div class='req-card'>
                    <b>User Name:</b> {{ req.name }}<br>
                    <b>Number:</b> {{ req.number }}<br>
                    <b>SIM Detect:</b> {{ req.sim }}<br><br>
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
                bot.send_message(req_data['chat_id'], "❌ Your giveaway request was Rejected by Admin.")
                fb_delete(f"/requests/{req_id}")
                msg = "Request Rejected."
            
            elif action == 'success' and req_data:
                img_url = request.form['img_url']
                win_msg = "🎉 <b>Congratulations!</b> Your request was approved."
                try:
                    bot.send_photo(req_data['chat_id'], img_url, caption=win_msg, parse_mode="HTML")
                except Exception as e:
                    pass

                all_users = fb_get("/users")
                if all_users:
                    tg_name = req_data.get('name', 'User')
                    broadcast_msg = f"🏆 <b>GIVEAWAY WINNER ANNOUNCEMENT</b> 🏆\n\n👤 <b>Winner:</b> {tg_name}\n🎉 <b>Giveaway Winner!</b>\nCongratulations to them!"
                    for uid in all_users.keys():
                        try:
                            bot.send_photo(uid, img_url, caption=broadcast_msg, parse_mode="HTML")
                        except:
                            pass
                
                fb_delete(f"/requests/{req_id}")
                msg = "Request Success & Broadcasted!"

    packs = fb_get("/packs") or {}
    requests_data = fb_get("/requests") or {}
    return render_template_string(ADMIN_HTML, msg=msg, packs=packs, requests_data=requests_data)

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
    time.sleep(1) # Fix 3: Thoda delay taaki Telegram purana webhook clean kar de
    url = request.host_url + BOT_TOKEN
    bot.set_webhook(url=url)
    return f"✅ Webhook successfully set to: {url}", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
