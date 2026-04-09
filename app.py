"""
Servidor Webhook Telegram → ClickUp
Roda 24/7 no Render.com
"""

import os
import json
import requests
from flask import Flask, request, jsonify
from datetime import datetime, timedelta

app = Flask(__name__)

# ==================== CONFIGURAÇÕES ====================
TELEGRAM_TOKEN = "8070425563:AAHohccqjyZ9nBTiJ4OtczjHo6-OKRobYjg"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ClickUp
CLICKUP_TOKEN = os.environ.get("CLICKUP_TOKEN", "")
CLICKUP_WORKSPACE_ID = "9011864477"
CLICKUP_LIST_ID = "901113530854"
CLICKUP_API = "https://api.clickup.com/api/v2"

# Webhook URL
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")

# ==================== ROTAS ====================

@app.route("/", methods=["GET"])
def health():
    """Verificar se o servidor está vivo"""
    return jsonify({
        "status": "🟢 OK",
        "service": "Telegram → ClickUp Automation",
        "timestamp": datetime.now().isoformat(),
        "webhook_url": f"{WEBHOOK_URL}/webhook"
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    """Recebe updates do Telegram"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"ok": True})
        
        if "message" not in data:
            return jsonify({"ok": True})
        
        message = data["message"]
        chat_id = message.get("chat", {}).get("id")
        user_name = message.get("from", {}).get("first_name", "Usuário")
        
        if not chat_id:
            return jsonify({"ok": True})
        
        # Processa diferentes tipos de mensagem
        task_data = None
        
        if "text" in message:
            texto = message["text"]
            print(f"📝 [{user_name}] Texto: {texto}")
            task_data = parse_message(texto)
        
        elif "voice" in message:
            print(f"🎤 [{user_name}] Áudio de voz")
            send_message(chat_id, "🎤 Áudio recebido! (Transcrição em desenvolvimento)")
        
        elif "audio" in message:
            print(f"🎵 [{user_name}] Arquivo de áudio")
            send_message(chat_id, "🎵 Arquivo de áudio recebido!")
        
        # Se conseguiu extrair tarefa
        if task_data:
            try:
                task_id = create_clickup_task(task_data)
                response_text = f"✅ Tarefa criada!\n\n📌 {task_data['name']}"
                if task_data.get("due_date"):
                    response_text += f"\n⏰ Prazo: {task_data['due_date']}"
                
                send_message(chat_id, response_text)
                print(f"✅ Tarefa criada no ClickUp: {task_id}")
            
            except Exception as e:
                print(f"❌ Erro ao criar tarefa: {str(e)}")
                send_message(chat_id, f"❌ Erro: {str(e)}")
        
        return jsonify({"ok": True})
    
    except Exception as e:
        print(f"❌ Erro no webhook: {str(e)}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/setup_webhook", methods=["GET"])
def setup_webhook():
    """Ativa o webhook no Telegram"""
    try:
        webhook_url = f"{WEBHOOK_URL}/webhook"
        url = f"{TELEGRAM_API}/setWebhook"
        
        response = requests.post(url, json={"url": webhook_url})
        data = response.json()
        
        print(f"🔗 Webhook configurado: {webhook_url}")
        return jsonify(data)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get_webhook_info", methods=["GET"])
def get_webhook_info():
    """Obtém informações do webhook"""
    try:
        url = f"{TELEGRAM_API}/getWebhookInfo"
        response = requests.get(url)
        return jsonify(response.json())
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== FUNÇÕES ====================

def parse_message(texto):
    """Parse da mensagem para extrair dados da tarefa"""
    if not texto or len(texto.strip()) == 0:
        return None
    
    task_data = {
        "name": texto.strip(),
        "due_date": None,
        "priority": None,
        "description": ""
    }
    
    # Detecta prioridade
    texto_lower = texto.lower()
    
    if any(word in texto_lower for word in ["urgente", "urgencia", "asap"]):
        task_data["priority"] = "urgent"
        task_data["name"] = remove_words(texto, ["urgente", "urgencia", "asap"])
    elif any(word in texto_lower for word in ["importante", "alta", "high"]):
        task_data["priority"] = "high"
        task_data["name"] = remove_words(texto, ["importante", "alta", "high"])
    
    # Detecta datas
    if any(word in texto_lower for word in ["hoje", "today"]):
        task_data["due_date"] = get_today_date()
        task_data["name"] = remove_words(texto, ["hoje", "today"])
    elif any(word in texto_lower for word in ["amanhã", "tomorrow"]):
        task_data["due_date"] = get_tomorrow_date()
        task_data["name"] = remove_words(texto, ["amanhã", "tomorrow"])
    elif any(word in texto_lower for word in ["próxima segunda", "segunda", "monday"]):
        task_data["due_date"] = get_next_monday()
        task_data["name"] = remove_words(texto, ["próxima segunda", "segunda", "monday"])
    
    # Limpa nome
    task_data["name"] = task_data["name"].strip()
    
    # Adiciona emoji se não tiver
    if not has_emoji(task_data["name"]):
        task_data["name"] = "📋 " + task_data["name"]
    
    return task_data

def remove_words(texto, words):
    """Remove palavras do texto"""
    result = texto
    for word in words:
        result = result.replace(word, "").replace(word.upper(), "")
    return result.strip()

def has_emoji(text):
    """Verifica se texto tem emoji"""
    return any(ord(char) > 127 for char in text)

def get_today_date():
    """Retorna data de hoje em YYYY-MM-DD"""
    return datetime.now().strftime("%Y-%m-%d")

def get_tomorrow_date():
    """Retorna data de amanhã em YYYY-MM-DD"""
    tomorrow = datetime.now() + timedelta(days=1)
    return tomorrow.strftime("%Y-%m-%d")

def get_next_monday():
    """Retorna próxima segunda-feira"""
    today = datetime.now()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_monday = today + timedelta(days=days_ahead)
    return next_monday.strftime("%Y-%m-%d")

def send_message(chat_id, text):
    """Envia mensagem no Telegram"""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=data)
        return response.json()
    except Exception as e:
        print(f"❌ Erro ao enviar mensagem: {str(e)}")
        return None

def create_clickup_task(task_data):
    """Cria tarefa no ClickUp"""
    if not CLICKUP_TOKEN:
        raise Exception("❌ Token ClickUp não configurado! Adicione via variável CLICKUP_TOKEN")
    
    url = f"{CLICKUP_API}/list/{CLICKUP_LIST_ID}/task"
    
    payload = {
        "name": task_data["name"],
        "description": task_data.get("description", ""),
    }
    
    # Adiciona prioridade se tiver
    if task_data.get("priority") == "urgent":
        payload["priority"] = 1
    elif task_data.get("priority") == "high":
        payload["priority"] = 2
    
    # Adiciona data se tiver
    if task_data.get("due_date"):
        due_date_obj = datetime.strptime(task_data["due_date"], "%Y-%m-%d")
        payload["due_date"] = int(due_date_obj.timestamp() * 1000)
    
    headers = {
        "Authorization": CLICKUP_TOKEN,
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code != 200:
        error_data = response.json()
        raise Exception(f"Erro ClickUp: {error_data.get('err', 'Desconhecido')}")
    
    task = response.json()
    return task.get("id")

# ==================== STARTUP ====================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    print("""
╔════════════════════════════════════════════════════════════╗
║         🤖 AUTOMAÇÃO TELEGRAM → CLICKUP                   ║
║              Rodando no Render.com                         ║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  Bot Telegram: @promavassistente_bot                      ║
║  Webhook: /webhook                                        ║
║  Status: /                                                ║
║  Setup: /setup_webhook                                   ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
""")
    
    app.run(host="0.0.0.0", port=port, debug=False)
