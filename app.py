from flask import Flask, render_template, request, jsonify
import os
import io
import pandas as pd

app = Flask(__name__, template_folder="templates")

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("onboarding.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/waitlist", methods=["POST"])
def waitlist():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    if not email or "@" not in email:
        return jsonify({"success": False, "message": "Adresse e-mail invalide."}), 400
    print(f"[Waitlist] Nouvel inscrit : {email}")
    return jsonify({"success": True, "message": "Bienvenue !", "redirect": "/dashboard"})


@app.route("/api/upload", methods=["POST"])
def upload():
    """
    Reçoit un fichier CSV ou Excel, détecte les colonnes automatiquement,
    analyse le stock et retourne les données structurées au dashboard.
    """
    if "file" not in request.files:
        return jsonify({"success": False, "message": "Aucun fichier reçu."}), 400

    file = request.files["file"]
    filename = file.filename.lower()

    if not (filename.endswith(".csv") or filename.endswith(".xlsx") or filename.endswith(".xls")):
        return jsonify({"success": False, "message": "Format non supporté. Utilisez .xlsx ou .csv"}), 400

    try:
        # ── Lecture du fichier ─────────────────────────────────────
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file.read()), encoding="utf-8", sep=None, engine="python")
        else:
            df = pd.read_excel(io.BytesIO(file.read()))

        df.columns = df.columns.str.strip().str.lower()

        # ── Détection automatique des colonnes ─────────────────────
        col_name  = _find_col(df, ["nom", "name", "produit", "medicament", "médicament", "designation", "désignation", "libelle", "libellé", "article"])
        col_qty   = _find_col(df, ["quantite", "quantité", "qty", "stock", "qte", "qté", "nombre", "nb"])
        col_exp   = _find_col(df, ["peremption", "péremption", "expiration", "date_exp", "exp", "dlc", "date peremption", "date péremption"])
        col_price = _find_col(df, ["prix", "price", "pu", "prix unitaire", "tarif"])

        if not col_name:
            return jsonify({"success": False, "message": "Colonne produit introuvable. Assurez-vous d'avoir une colonne 'Nom', 'Produit' ou 'Médicament'."}), 400
        if not col_qty:
            return jsonify({"success": False, "message": "Colonne quantité introuvable. Assurez-vous d'avoir une colonne 'Quantité', 'Stock' ou 'Qty'."}), 400

        # ── Analyse du stock ───────────────────────────────────────
        items = []
        urgent_count  = 0
        warning_count = 0
        ok_count      = 0
        dormant_count = 0

        for _, row in df.iterrows():
            name = str(row[col_name]).strip()
            if not name or name.lower() in ["nan", "none", ""]:
                continue

            try:
                qty = int(float(str(row[col_qty]).replace(",", ".").strip()))
            except:
                qty = 0

            # Statut par défaut basé sur quantité
            status = "ok"
            label  = "● Optimal"
            action = "Voir les ventes"
            qty_label = f"{qty} boîtes"

            # Analyse péremption si colonne dispo
            days_left = None
            if col_exp:
                try:
                    exp_date = pd.to_datetime(row[col_exp], dayfirst=True, errors="coerce")
                    if pd.notna(exp_date):
                        days_left = (exp_date - pd.Timestamp.now()).days
                        if days_left < 0:
                            status = "urgent"
                            label  = "● Périmé"
                            action = "Retirer du stock"
                            qty_label = f"{qty} boîtes — PÉRIMÉ"
                        elif days_left <= 30:
                            status = "urgent"
                            label  = "● Urgent"
                            action = "Proposer une remise"
                            qty_label = f"{qty} boîtes — périme dans {days_left} j"
                        elif days_left <= 60:
                            status = "urgent"
                            label  = "● Urgent"
                            action = "Proposer une remise"
                            qty_label = f"{qty} boîtes — périme dans {days_left} j"
                        elif days_left <= 90:
                            status = "warning"
                            label  = "● À surveiller"
                            action = "Voir la recommandation"
                            qty_label = f"{qty} boîtes — périme dans {days_left} j"
                except:
                    pass

            # Quantité faible → dormant ou warning
            if days_left is None:
                if qty == 0:
                    status = "urgent"
                    label  = "● Rupture"
                    action = "Commander urgent"
                    qty_label = "0 boîte — rupture"
                elif qty <= 10:
                    status = "warning"
                    label  = "● À surveiller"
                    action = "Commander bientôt"
                    qty_label = f"{qty} boîtes — stock bas"
                elif qty >= 500:
                    status = "dormant"
                    label  = "● Dormant"
                    action = "Voir les alternatives"

            # Compteurs
            if status == "urgent":   urgent_count  += 1
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

        # ── KPIs ───────────────────────────────────────────────────
        total = len(items)
        sante_pct = round((ok_count / total * 100)) if total > 0 else 0

        return jsonify({
            "success":  True,
            "filename": file.filename,
            "total":    total,
            "items":    items,
            "kpis": {
                "urgent":   urgent_count,
                "warning":  warning_count,
                "ok":       ok_count,
                "dormant":  dormant_count,
                "sante_pct": sante_pct,
            }
        })

    except Exception as e:
        print(f"[Upload Error] {e}")
        return jsonify({"success": False, "message": f"Erreur lors de la lecture du fichier : {str(e)}"}), 500


def _find_col(df, candidates):
    """Trouve la première colonne du DataFrame qui correspond à un des candidats."""
    for c in candidates:
        for col in df.columns:
            if c in col.replace("-", " ").replace("_", " "):
                return col
    return None


# ─── Lancement ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
                             
