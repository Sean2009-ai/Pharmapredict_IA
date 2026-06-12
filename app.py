from flask import Flask, render_template, request, jsonify, session, send_from_directory
import os, io, datetime, json
import pandas as pd

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "pharmapredict-secret-2026")

# ─── Supabase (optionnel — les données vivent dans IndexedDB côté client) ─────
try:
    from supabase import create_client
    _sup_url = os.environ.get("SUPABASE_URL","")
    _sup_key = os.environ.get("SUPABASE_KEY","")
    _supabase = create_client(_sup_url, _sup_key) if _sup_url and _sup_key else None
except Exception:
    _supabase = None

def db(): return _supabase

# ─── PWA routes ───────────────────────────────────────────────────────────────
@app.route("/manifest.json")
def manifest():
    return send_from_directory("templates", "manifest.json",
                               mimetype="application/manifest+json")

@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js",
                               mimetype="application/javascript")

# ─── Saisons & pathologies ─────────────────────────────────────────────────────
SAISONS = {
    "afrique_ouest":  {"debut": 6,  "fin": 10, "label": "Afrique de l'Ouest"},
    "afrique_centre": {"debut": 3,  "fin": 11, "label": "Afrique Centrale"},
    "afrique_est":    {"debut": 3,  "fin": 5,  "label": "Afrique de l'Est"},
    "afrique_sud":    {"debut": 11, "fin": 3,  "label": "Afrique Australe"},
}

SAISONNALITE = {
    "paludisme": {
        "mots_cles": ["artemether", "artesunat", "artesunate", "lumefantrine", "luméfantrine",
                      "quinine", "coartem", "chloroquine", "antipaludeen", "antipaludéen",
                      "malarone", "fansidar"],
        "conseil": "Augmenter le stock — saison paludisme imminente",
        "boost": 2.0,
    },
    "diarrhee": {
        "mots_cles": ["sro", "rehidratation", "réhydratation", "zinc", "metronidazole",
                      "cotrimoxazole", "ciprofloxacine", "dioralyte"],
        "conseil": "Forte demande attendue — maladies hydriques en hausse",
        "boost": 1.5,
    },
    "infections_respiratoires": {
        "mots_cles": ["amoxicilline", "amoxicillin", "azithromycine", "paracetamol",
                      "paracétamol", "ibuprofen", "ibuprofene", "vitamine c"],
        "conseil": "Demande accrue — infections respiratoires en saison fraîche",
        "boost": 1.3,
    },
    "prevention": {
        "mots_cles": ["moustiquaire", "repulsif", "répulsif", "insecticide"],
        "conseil": "Prévention paludisme — forte demande en saison des pluies",
        "boost": 2.0,
    },
}

def _get_saison_context(region="afrique_ouest"):
    today   = datetime.date.today()
    mois    = today.month
    saison  = SAISONS.get(region, SAISONS["afrique_ouest"])
    debut, fin = saison["debut"], saison["fin"]
    alertes = []
    if debut <= fin:
        en_saison = debut <= mois <= fin
    else:
        en_saison = mois >= debut or mois <= fin

    if en_saison:
        alertes.append({"type": "saison_active", "icon": "🌧️",
            "titre": "Saison des pluies en cours",
            "message": f"Saison active en {saison['label']}. Maintenez vos stocks antipaludéens élevés.",
            "niveau": "warning"})
    else:
        annee = today.year
        prochaine = datetime.date(annee, debut, 1)
        if prochaine < today:
            prochaine = datetime.date(annee + 1, debut, 1)
        jours = (prochaine - today).days
        if jours <= 45:
            alertes.append({"type": "saison_proche", "icon": "🌧️",
                "titre": f"Saison des pluies dans {jours} jours",
                "message": f"Approvisionnez-vous en antipaludéens avant le {prochaine.strftime('%d/%m/%Y')}.",
                "niveau": "urgent", "jours": jours})
        elif jours <= 90:
            alertes.append({"type": "saison_proche", "icon": "🌧️",
                "titre": f"Saison des pluies dans {jours} jours",
                "message": f"Planifiez vos commandes antipaludéens d'ici {jours} jours.",
                "niveau": "info", "jours": jours})
    return alertes, en_saison

def _analyser_saisonnalite(items, region="afrique_ouest"):
    alertes_saison, en_saison = _get_saison_context(region)
    previsions = []
    for item in items:
        nom_lower = item["name"].lower()
        for patho, data in SAISONNALITE.items():
            for mot in data["mots_cles"]:
                if mot in nom_lower:
                    boost = data["boost"] if en_saison else (data["boost"] * 0.7 if alertes_saison else 1.0)
                    previsions.append({
                        "name": item["name"], "status": item["status"], "qty": item["qty"],
                        "patho": patho, "conseil": data["conseil"],
                        "boost": round(boost, 1), "priorite": "haute" if boost >= 2.0 else "moyenne",
                    })
                    break
    return alertes_saison, previsions

def _find_col(df, candidates):
    for c in candidates:
        for col in df.columns:
            if c in col.replace("-", " ").replace("_", " "):
                return col
    return None

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("onboarding.html")

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

# ── Inscription / connexion ────────────────────────────────────────────────────
@app.route("/api/waitlist", methods=["POST"])
def waitlist():
    data  = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    if not email or "@" not in email:
        return jsonify({"success": False, "message": "Adresse e-mail invalide."}), 400

    # Sauvegarder dans Supabase
    if db():
        try:
            existing = db().table("users").select("id").eq("email", email).execute()
            if not existing.data:
                db().table("users").insert({
                    "email":      email,
                    "plan":       "demo",
                    "created_at": datetime.datetime.utcnow().isoformat(),
                }).execute()
        except Exception as e:
            print(f"[Supabase] Erreur inscription : {e}")

    session["email"] = email
    print(f"[Waitlist] Nouvel inscrit : {email}")
    return jsonify({"success": True, "message": "Bienvenue !", "redirect": "/dashboard"})

# ── Upload & analyse stock ─────────────────────────────────────────────────────
@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"success": False, "message": "Aucun fichier reçu."}), 400

    file     = request.files["file"]
    filename = file.filename.lower()
    region   = request.form.get("region", "afrique_ouest")
    email    = session.get("email", "anonymous")

    if not (filename.endswith(".csv") or filename.endswith(".xlsx") or filename.endswith(".xls")):
        return jsonify({"success": False, "message": "Format non supporté. Utilisez .xlsx ou .csv"}), 400

    try:
        raw = file.read()
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(raw), encoding="utf-8", sep=None, engine="python")
        else:
            df = pd.read_excel(io.BytesIO(raw))

        df.columns = df.columns.str.strip().str.lower()

        col_name  = _find_col(df, ["nom", "name", "produit", "medicament", "médicament",
                                    "designation", "désignation", "libelle", "libellé", "article"])
        col_qty   = _find_col(df, ["quantite", "quantité", "qty", "stock", "qte", "qté", "nombre", "nb"])
        col_exp   = _find_col(df, ["peremption", "péremption", "expiration", "date_exp",
                                    "exp", "dlc", "date peremption", "date péremption"])
        col_price = _find_col(df, ["prix", "price", "pu", "prix unitaire", "tarif"])

        if not col_name:
            return jsonify({"success": False, "message": "Colonne produit introuvable."}), 400
        if not col_qty:
            return jsonify({"success": False, "message": "Colonne quantité introuvable."}), 400

        items = []
        urgent_count = warning_count = ok_count = dormant_count = 0

        for _, row in df.iterrows():
            name = str(row[col_name]).strip()
            if not name or name.lower() in ["nan", "none", ""]:
                continue
            try:
                qty = int(float(str(row[col_qty]).replace(",", ".").strip()))
            except:
                qty = 0

            status, label, action, qty_label, days_left = "ok", "● Optimal", "Voir les ventes", f"{qty} boîtes", None

            if col_exp:
                try:
                    exp_date = pd.to_datetime(row[col_exp], dayfirst=True, errors="coerce")
                    if pd.notna(exp_date):
                        days_left = (exp_date - pd.Timestamp.now()).days
                        if days_left < 0:
                            status, label, action = "urgent", "● Périmé", "Retirer du stock"
                            qty_label = f"{qty} boîtes — PÉRIMÉ"
                        elif days_left <= 60:
                            status, label, action = "urgent", "● Urgent", "Proposer une remise"
                            qty_label = f"{qty} boîtes — périme dans {days_left} j"
                        elif days_left <= 90:
                            status, label, action = "warning", "● À surveiller", "Voir la recommandation"
                            qty_label = f"{qty} boîtes — périme dans {days_left} j"
                except:
                    pass

            if days_left is None:
                if qty == 0:
                    status, label, action, qty_label = "urgent", "● Rupture", "Commander urgent", "0 boîte — rupture"
                elif qty <= 10:
                    status, label, action, qty_label = "warning", "● À surveiller", "Commander bientôt", f"{qty} boîtes — stock bas"
                elif qty >= 500:
                    status, label, action = "dormant", "● Dormant", "Voir les alternatives"

            if status == "urgent":    urgent_count  += 1
            elif status == "warning": warning_count += 1
            elif status == "dormant": dormant_count += 1
            else:                     ok_count      += 1

            item = {"name": name, "qty": qty_label, "status": status, "label": label, "action": action}
            if col_price:
                try:
                    item["price"] = float(str(row[col_price]).replace(",", ".").replace(" ", "").strip())
                except:
                    pass
            items.append(item)

        alertes_saison, previsions = _analyser_saisonnalite(items, region)
        total     = len(items)
        sante_pct = round((ok_count / total * 100)) if total > 0 else 0

        # ── Sauvegarder dans Supabase ──────────────────────────────
        if db():
            try:
                import_id = None
                # 1. Enregistrer l'import
                imp = db().table("imports").insert({
                    "email":       email,
                    "filename":    file.filename,
                    "total":       total,
                    "urgent":      urgent_count,
                    "warning":     warning_count,
                    "ok":          ok_count,
                    "dormant":     dormant_count,
                    "sante_pct":   sante_pct,
                    "region":      region,
                    "imported_at": datetime.datetime.utcnow().isoformat(),
                }).execute()
                if imp.data:
                    import_id = imp.data[0]["id"]

                # 2. Supprimer l'ancien stock de cet utilisateur
                db().table("stock_items").delete().eq("email", email).execute()

                # 3. Insérer le nouveau stock par lots de 100
                rows = [{"email": email, "import_id": import_id, **item} for item in items]
                for i in range(0, len(rows), 100):
                    db().table("stock_items").insert(rows[i:i+100]).execute()

                print(f"[Supabase] Stock sauvegardé : {total} références pour {email}")
            except Exception as e:
                print(f"[Supabase] Erreur sauvegarde stock : {e}")

        return jsonify({
            "success": True, "filename": file.filename, "total": total,
            "items": items,
            "kpis": {"urgent": urgent_count, "warning": warning_count,
                     "ok": ok_count, "dormant": dormant_count, "sante_pct": sante_pct},
            "saison": {"alertes": alertes_saison, "previsions": previsions,
                       "region": SAISONS.get(region, SAISONS["afrique_ouest"])["label"]},
        })

    except Exception as e:
        print(f"[Upload Error] {e}")
        return jsonify({"success": False, "message": f"Erreur lecture fichier : {str(e)}"}), 500

# ── Charger le stock depuis Supabase ──────────────────────────────────────────
@app.route("/api/stock", methods=["GET"])
def get_stock():
    email = session.get("email")
    if not email:
        return jsonify({"success": False, "message": "Non connecté"}), 401
    if not db():
        return jsonify({"success": False, "message": "Base de données non configurée"}), 503
    try:
        items = db().table("stock_items").select("*").eq("email", email).order("status").execute()
        return jsonify({"success": True, "items": items.data or []})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ── Historique des imports ─────────────────────────────────────────────────────
@app.route("/api/imports", methods=["GET"])
def get_imports():
    email = session.get("email")
    if not email:
        return jsonify({"success": False, "message": "Non connecté"}), 401
    if not db():
        return jsonify({"success": False, "message": "Base de données non configurée"}), 503
    try:
        imports = db().table("imports").select("*").eq("email", email)\
                      .order("imported_at", desc=True).limit(20).execute()
        return jsonify({"success": True, "imports": imports.data or []})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ── Sauvegarder config Email ──────────────────────────────────────────────────
@app.route("/api/email/config", methods=["POST"])
def save_email_config():
    data        = request.get_json(silent=True) or {}
    user_email  = session.get("email")
    if not user_email:
        return jsonify({"success": False, "message": "Non connecté"}), 401
    if not db():
        return jsonify({"success": True, "message": "Config locale (DB non configurée)"})
    try:
        db().table("users").update({
            "notif_email": data.get("notif_email", user_email),
            "email_freq":  data.get("freq", "lundi"),
        }).eq("email", user_email).execute()
        return jsonify({"success": True, "message": "Configuration email sauvegardée ✅"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ── Envoyer email via Brevo ───────────────────────────────────────────────────
def _send_brevo_email(to_email, subject, html_content):
    """Envoie un email via l'API Brevo (ex-Sendinblue)."""
    api_key = os.environ.get("BREVO_API_KEY", "")
    if not api_key:
        raise ValueError("BREVO_API_KEY non configurée dans les variables d'environnement.")

    import urllib.request, json as _json
    payload = {
        "sender":     {"name": "PharmaPredict IA", "email": "noreply@pharmapredict.africa"},
        "to":         [{"email": to_email}],
        "subject":    subject,
        "htmlContent": html_content,
    }
    data    = _json.dumps(payload).encode("utf-8")
    req     = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=data,
        headers={"Content-Type": "application/json", "api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return _json.loads(r.read().decode())


def _build_email_html(items, kpis, saison_alertes):
    """Génère le HTML de l'email de rapport."""
    today    = datetime.datetime.now().strftime("%d/%m/%Y")
    urgents  = [i for i in items if i["status"] == "urgent"]
    warnings = [i for i in items if i["status"] == "warning"]

    urgent_rows  = "".join(f"<tr><td style='padding:8px;border-bottom:1px solid #1e4a34;color:#e8f5ee'>{i['name']}</td><td style='padding:8px;border-bottom:1px solid #1e4a34;color:#e05c5c'>{i['qty']}</td><td style='padding:8px;border-bottom:1px solid #1e4a34;color:#e05c5c'>{i['label']}</td></tr>" for i in urgents[:10])
    warning_rows = "".join(f"<tr><td style='padding:8px;border-bottom:1px solid #1e4a34;color:#e8f5ee'>{i['name']}</td><td style='padding:8px;border-bottom:1px solid #1e4a34;color:#f5a623'>{i['qty']}</td><td style='padding:8px;border-bottom:1px solid #1e4a34;color:#f5a623'>{i['label']}</td></tr>" for i in warnings[:10])
    saison_html  = "".join(f"<p style='background:#102b1e;border-left:3px solid #2ecc8a;padding:10px 14px;border-radius:4px;margin:8px 0;color:#e8f5ee'>{a['icon']} <strong>{a['titre']}</strong><br><span style='color:#7aad90;font-size:13px'>{a['message']}</span></p>" for a in saison_alertes)

    return f"""
<!DOCTYPE html><html><body style='background:#05150f;font-family:Inter,sans-serif;color:#e8f5ee;padding:0;margin:0'>
<div style='max-width:600px;margin:0 auto;padding:32px 20px'>
  <h1 style='font-size:22px;color:#2ecc8a;margin-bottom:4px'>💊 PharmaPredict IA</h1>
  <p style='color:#7aad90;font-size:14px;margin-bottom:28px'>Rapport du {today}</p>

  <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:24px'>
    <div style='background:#0d2318;border:1px solid #1e4a34;border-radius:12px;padding:18px;text-align:center'>
      <div style='font-size:28px;font-weight:800;color:#e05c5c'>{kpis["urgent"]}</div>
      <div style='font-size:12px;color:#7aad90'>Urgents</div>
    </div>
    <div style='background:#0d2318;border:1px solid #1e4a34;border-radius:12px;padding:18px;text-align:center'>
      <div style='font-size:28px;font-weight:800;color:#f5a623'>{kpis["warning"]}</div>
      <div style='font-size:12px;color:#7aad90'>À surveiller</div>
    </div>
    <div style='background:#0d2318;border:1px solid #1e4a34;border-radius:12px;padding:18px;text-align:center'>
      <div style='font-size:28px;font-weight:800;color:#2ecc8a'>{kpis["ok"]}</div>
      <div style='font-size:12px;color:#7aad90'>Optimaux</div>
    </div>
    <div style='background:#0d2318;border:1px solid #1e4a34;border-radius:12px;padding:18px;text-align:center'>
      <div style='font-size:28px;font-weight:800;color:#2ecc8a'>{kpis["sante_pct"]} %</div>
      <div style='font-size:12px;color:#7aad90'>Santé stock</div>
    </div>
  </div>

  {"<h2 style='font-size:16px;color:#e05c5c;margin-bottom:12px'>🔴 Urgents</h2><table style='width:100%;border-collapse:collapse;background:#0d2318;border-radius:12px;overflow:hidden;margin-bottom:24px'><tr style='background:#102b1e'><th style='padding:10px 8px;text-align:left;color:#7aad90;font-size:12px'>Produit</th><th style='padding:10px 8px;text-align:left;color:#7aad90;font-size:12px'>Stock</th><th style='padding:10px 8px;text-align:left;color:#7aad90;font-size:12px'>Statut</th></tr>" + urgent_rows + "</table>" if urgents else ""}
  {"<h2 style='font-size:16px;color:#f5a623;margin-bottom:12px'>🟡 À surveiller</h2><table style='width:100%;border-collapse:collapse;background:#0d2318;border-radius:12px;overflow:hidden;margin-bottom:24px'><tr style='background:#102b1e'><th style='padding:10px 8px;text-align:left;color:#7aad90;font-size:12px'>Produit</th><th style='padding:10px 8px;text-align:left;color:#7aad90;font-size:12px'>Stock</th><th style='padding:10px 8px;text-align:left;color:#7aad90;font-size:12px'>Statut</th></tr>" + warning_rows + "</table>" if warnings else ""}
  {"<h2 style='font-size:16px;color:#2ecc8a;margin-bottom:12px'>🌧️ Prévisions saisonnières</h2>" + saison_html if saison_alertes else ""}

  <div style='text-align:center;margin-top:32px'>
    <a href='https://pharmapredict-ia-czd7.onrender.com/dashboard' style='background:#2ecc8a;color:#0a3d2e;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:700;font-size:14px'>Ouvrir mon tableau de bord →</a>
  </div>
  <p style='text-align:center;color:#7aad90;font-size:11px;margin-top:24px'>PharmaPredict IA · Conçu pour l'Afrique<br>Pour vous désabonner, modifiez vos préférences dans le dashboard.</p>
</div></body></html>"""


@app.route("/api/email/send", methods=["POST"])
def email_send():
    data       = request.get_json(silent=True) or {}
    user_email = session.get("email", "anonymous")
    to_email   = data.get("to", user_email)
    items      = data.get("items", [])
    kpis       = data.get("kpis", {"urgent": 0, "warning": 0, "ok": 0, "sante_pct": 0})
    saison     = data.get("saison_alertes", [])
    subject    = data.get("subject", f"💊 PharmaPredict IA — Rapport du {datetime.datetime.now().strftime('%d/%m/%Y')}")

    if not to_email:
        return jsonify({"success": False, "message": "Email destinataire manquant"}), 400

    try:
        html = _build_email_html(items, kpis, saison)
        _send_brevo_email(to_email, subject, html)

        # Log dans Supabase
        if db():
            try:
                db().table("email_logs").insert({
                    "email":   user_email,
                    "to":      to_email,
                    "subject": subject,
                    "status":  "sent",
                    "sent_at": datetime.datetime.utcnow().isoformat(),
                }).execute()
            except Exception as e:
                print(f"[Supabase] Erreur log email : {e}")

        print(f"[Email] Envoyé à {to_email}")
        return jsonify({"success": True, "message": f"Email envoyé à {to_email} ✅"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Erreur envoi : {str(e)}"}), 500


@app.route("/api/email/logs", methods=["GET"])
def email_logs():
    user_email = session.get("email")
    if not user_email or not db():
        return jsonify({"success": True, "logs": []})
    try:
        logs = db().table("email_logs").select("*").eq("email", user_email)\
                   .order("sent_at", desc=True).limit(20).execute()
        return jsonify({"success": True, "logs": logs.data or []})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ─── Lancement ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
