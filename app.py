"""
PharmaPredict AI — Serveur principal Flask
Deploy : Render.com
Start command : gunicorn app:app
"""

import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

app = Flask(__name__, template_folder="templates")
CORS(app)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")
PORT = int(os.environ.get("PORT", 5000))

# ── TODO : remplacer par vos appels Supabase ──────────────────────────────────
# from supabase import create_client
# supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

def get_pharmacies_from_db(plan="all", status="all", q=""):
    """Récupère les pharmacies depuis la base de données."""
    # TODO : supabase.table("pharmacies").select("*").execute()
    return []

def get_inventory_from_db(pharmacy_id):
    """Récupère le stock d'une pharmacie."""
    # TODO : supabase.table("inventory").select("*").eq("pharmacy_id", pharmacy_id).execute()
    return []

def get_sales_history_from_db(pharmacy_id, product_id):
    """Récupère l'historique des ventes pour les prédictions."""
    # TODO : supabase.table("sales_history").select("*").eq("pharmacy_id", pharmacy_id).execute()
    return []

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("onboarding.html")

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "PharmaPredict AI", "version": "1.0.0"})

@app.route("/api/pharmacies")
def get_pharmacies():
    plan   = request.args.get("plan", "all")
    status = request.args.get("status", "all")
    q      = request.args.get("q", "").lower()
    data   = get_pharmacies_from_db(plan, status, q)
    return jsonify({"pharmacies": data, "total": len(data)})

@app.route("/api/pharmacies/<pharmacy_id>")
def get_pharmacy(pharmacy_id):
    # TODO : requête Supabase par id
    return jsonify({"error": "Non implémenté"}), 501

@app.route("/api/stats")
def get_stats():
    pharmacies = get_pharmacies_from_db()
    active = [p for p in pharmacies if p.get("status") == "active"]
    mrr    = sum(p.get("mrr", 0) for p in active)
    return jsonify({
        "mrr":          mrr,
        "arr":          mrr * 12,
        "active_count": len(active),
        "past_due":     len([p for p in pharmacies if p.get("status") == "past_due"]),
        "trial_count":  len([p for p in pharmacies if p.get("status") == "trial"]),
        "plan_distribution": {
            "solo":       {"count": sum(1 for p in active if p.get("plan") == "solo"),       "price": 25000},
            "croissance": {"count": sum(1 for p in active if p.get("plan") == "croissance"), "price": 60000},
            "empire":     {"count": sum(1 for p in active if p.get("plan") == "empire"),     "price": 150000},
        }
    })

@app.route("/api/inventory")
def get_inventory():
    pharmacy_id = request.args.get("pharmacy_id", "")
    data = get_inventory_from_db(pharmacy_id)
    return jsonify({
        "inventory": data,
        "summary": {
            "red":    sum(1 for i in data if i.get("status") == "red"),
            "yellow": sum(1 for i in data if i.get("status") == "yellow"),
            "green":  sum(1 for i in data if i.get("status") == "green"),
        }
    })

@app.route("/api/predictions")
def get_predictions():
    """
    Prédictions via Prophet.
    TODO : appeler le micro-service Prophet ou calculer ici avec pandas.
    """
    pharmacy_id = request.args.get("pharmacy_id", "")
    product     = request.args.get("product", "")
    # TODO : charger l'historique + lancer Prophet
    return jsonify({"pharmacy_id": pharmacy_id, "product": product, "predictions": []})

@app.route("/api/purchase-order")
def get_purchase_order():
    """
    Génère le bon de commande optimal.
    TODO : calculer depuis inventory + predictions.
    """
    pharmacy_id = request.args.get("pharmacy_id", "")
    return jsonify({
        "pharmacy_id":  pharmacy_id,
        "order_date":   datetime.today().strftime("%d/%m/%Y"),
        "valid_until":  (datetime.today() + timedelta(days=7)).strftime("%d/%m/%Y"),
        "lines":        [],
    })

@app.route("/api/savings")
def get_savings():
    """
    Rapport ROI mensuel.
    TODO : calculer depuis savings_reports Supabase.
    """
    pharmacy_id = request.args.get("pharmacy_id", "")
    return jsonify({
        "pharmacy_id":                pharmacy_id,
        "period":                     datetime.today().strftime("%B %Y"),
        "expired_drugs_avoided_fcfa": 0,
        "stockouts_avoided":          0,
        "total_savings_fcfa":         0,
        "subscription_cost_fcfa":     0,
        "roi_multiplier":             0,
    })

@app.route("/api/import", methods=["POST"])
def import_file():
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier fourni"}), 400
    f = request.files["file"]
    if not f.filename.endswith((".csv", ".xlsx", ".xls")):
        return jsonify({"error": "Format non supporté. Utilisez CSV ou Excel."}), 400
    # TODO : parser avec pandas, mapper les colonnes, insérer dans Supabase
    return jsonify({"status": "success", "message": "Fichier reçu — traitement en cours"})

@app.route("/api/whatsapp/send", methods=["POST"])
def send_whatsapp():
    data   = request.get_json() or {}
    number = data.get("number", "")
    # TODO : appel API WhatsApp Business
    # POST https://api.whatsapp.business/v1/messages
    # Authorization: Bearer WHATSAPP_TOKEN
    return jsonify({"status": "queued", "recipient": number})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
