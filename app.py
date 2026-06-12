from flask import Flask, render_template, jsonify, request, g
import sqlite3, os, hashlib, json
from datetime import datetime, timedelta
import random

app = Flask(__name__)

# ── Base de données locale (sur l'ordi de l'utilisateur) ─────────────────────
DB_PATH = os.path.join(os.path.expanduser("~"), "pharmapredict.db")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    c = db.cursor()

    # ── Tables ────────────────────────────────────────────────────────────────
    c.executescript("""
    CREATE TABLE IF NOT EXISTS utilisateurs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        mot_de_passe TEXT NOT NULL,
        role TEXT DEFAULT 'pharmacien',
        plan TEXT DEFAULT 'demo',
        actif INTEGER DEFAULT 1,
        cree_le TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS medicaments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        categorie TEXT,
        unite TEXT DEFAULT 'boîte',
        prix_achat REAL DEFAULT 0,
        prix_vente REAL DEFAULT 0,
        stock_actuel INTEGER DEFAULT 0,
        stock_minimum INTEGER DEFAULT 10,
        date_expiration TEXT,
        fournisseur TEXT,
        statut TEXT DEFAULT 'actif',
        cree_le TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS ventes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        medicament_id INTEGER NOT NULL,
        quantite INTEGER NOT NULL,
        prix_unitaire REAL NOT NULL,
        total REAL NOT NULL,
        date_vente TEXT DEFAULT (datetime('now')),
        utilisateur_id INTEGER,
        FOREIGN KEY (medicament_id) REFERENCES medicaments(id),
        FOREIGN KEY (utilisateur_id) REFERENCES utilisateurs(id)
    );

    CREATE TABLE IF NOT EXISTS alertes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        message TEXT NOT NULL,
        medicament_id INTEGER,
        niveau TEXT DEFAULT 'info',
        lue INTEGER DEFAULT 0,
        cree_le TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (medicament_id) REFERENCES medicaments(id)
    );

    CREATE TABLE IF NOT EXISTS parametres (
        cle TEXT PRIMARY KEY,
        valeur TEXT NOT NULL,
        description TEXT,
        modifie_le TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS commandes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fournisseur TEXT NOT NULL,
        medicament_id INTEGER NOT NULL,
        quantite INTEGER NOT NULL,
        statut TEXT DEFAULT 'en_attente',
        date_commande TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (medicament_id) REFERENCES medicaments(id)
    );
    """)

    # ── Données de démo ───────────────────────────────────────────────────────
    # Admin par défaut
    pwd_hash = hashlib.sha256("admin2026".encode()).hexdigest()
    c.execute("""
        INSERT OR IGNORE INTO utilisateurs (nom, email, mot_de_passe, role, plan)
        VALUES ('Administrateur', 'admin@pharmapredict.ai', ?, 'admin', 'reseau')
    """, (pwd_hash,))

    # Paramètres par défaut
    params = [
        ("pharmacie_nom", "Ma Pharmacie", "Nom de la pharmacie"),
        ("pharmacie_ville", "Dakar", "Ville"),
        ("pharmacie_pays", "Sénégal", "Pays"),
        ("whatsapp_actif", "0", "Alertes WhatsApp activées"),
        ("whatsapp_numero", "", "Numéro WhatsApp"),
        ("alerte_stock_min", "10", "Seuil alerte stock bas"),
        ("alerte_expiration_jours", "60", "Jours avant expiration pour alerter"),
        ("devise", "FCFA", "Devise utilisée"),
        ("fournisseur_principal", "Laborex", "Grossiste principal"),
    ]
    for cle, valeur, desc in params:
        c.execute("INSERT OR IGNORE INTO parametres (cle, valeur, description) VALUES (?,?,?)",
                  (cle, valeur, desc))

    # Médicaments de démonstration
    meds = [
        ("Paracétamol 500 mg", "Antalgique", "boîte", 800, 1500, 320, 20, "2026-12-01", "Laborex"),
        ("Artéméther-Luméfantrine", "Antipaludéen", "boîte", 3500, 6000, 180, 30, "2025-09-15", "Ubipharm"),
        ("Amoxicilline 1 g", "Antibiotique", "boîte", 2000, 3800, 42, 25, "2025-08-10", "Laborex"),
        ("Métronidazole 250 mg", "Antiparasitaire", "boîte", 600, 1200, 95, 15, "2026-03-20", "Ubipharm"),
        ("Ibuprofène 400 mg", "Anti-inflammatoire", "boîte", 900, 1700, 210, 20, "2026-11-30", "Laborex"),
        ("Ciprofloxacine 500 mg", "Antibiotique", "boîte", 2500, 4500, 67, 15, "2026-06-01", "COPHARM"),
        ("ORS / SRO Sachet", "Réhydratation", "sachet", 150, 300, 450, 50, "2027-01-01", "Laborex"),
        ("Cotrimoxazole 480 mg", "Antibiotique", "boîte", 500, 1000, 130, 20, "2026-08-15", "Ubipharm"),
        ("Mébendazole 100 mg", "Antiparasitaire", "boîte", 400, 800, 88, 10, "2026-10-01", "Laborex"),
        ("Acide folique 5 mg", "Vitamines", "boîte", 300, 600, 155, 15, "2027-03-01", "COPHARM"),
        ("Quinine 300 mg", "Antipaludéen", "boîte", 1200, 2200, 73, 20, "2025-11-20", "Ubipharm"),
        ("Doxycycline 100 mg", "Antibiotique", "boîte", 1800, 3200, 29, 15, "2025-07-30", "Laborex"),
    ]
    for m in meds:
        c.execute("""
            INSERT OR IGNORE INTO medicaments
            (nom, categorie, unite, prix_achat, prix_vente, stock_actuel, stock_minimum, date_expiration, fournisseur)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, m)

    # Ventes de démo (3 derniers mois)
    med_ids = [r[0] for r in c.execute("SELECT id FROM medicaments").fetchall()]
    for i in range(120):
        mid = random.choice(med_ids)
        row = c.execute("SELECT prix_vente FROM medicaments WHERE id=?", (mid,)).fetchone()
        if row:
            prix = row[0]
            qty = random.randint(1, 10)
            days_ago = random.randint(0, 90)
            date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT OR IGNORE INTO ventes (medicament_id, quantite, prix_unitaire, total, date_vente) VALUES (?,?,?,?,?)",
                      (mid, qty, prix, prix*qty, date))

    # Alertes de démo
    alertes = [
        ("stock_bas", "Stock bas : Amoxicilline 1 g (42 boîtes)", 3, "warning"),
        ("expiration", "Expiration proche : Artéméther-Luméfantrine (60j)", 2, "danger"),
        ("expiration", "Expiration proche : Doxycycline 100 mg (49j)", 12, "danger"),
        ("stock_bas", "Stock critique : Quinine 300 mg (29 boîtes)", 11, "warning"),
        ("info", "Import CSV de la semaine traité avec succès", None, "info"),
    ]
    for typ, msg, mid, niv in alertes:
        c.execute("INSERT OR IGNORE INTO alertes (type, message, medicament_id, niveau) VALUES (?,?,?,?)",
                  (typ, msg, mid, niv))

    db.commit()
    db.close()

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — Pages
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/admin")
def admin():
    return render_template("admin.html")

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

# ══════════════════════════════════════════════════════════════════════════════
# API — Auth
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/login", methods=["POST"])
def login():
    d = request.get_json()
    email = d.get("email", "")
    pwd = hashlib.sha256(d.get("password", "").encode()).hexdigest()
    db = get_db()
    user = db.execute(
        "SELECT id, nom, role, plan FROM utilisateurs WHERE email=? AND mot_de_passe=? AND actif=1",
        (email, pwd)
    ).fetchone()
    if user:
        return jsonify({"success": True, "user": dict(user)})
    return jsonify({"success": False, "message": "Email ou mot de passe incorrect"}), 401

@app.route("/api/signup", methods=["POST"])
def signup():
    d = request.get_json()
    nom = d.get("nom", "")
    email = d.get("email", "")
    pwd = hashlib.sha256(d.get("password", "").encode()).hexdigest()
    if not nom or not email:
        return jsonify({"success": False, "message": "Champs manquants"}), 400
    try:
        db = get_db()
        db.execute(
            "INSERT INTO utilisateurs (nom, email, mot_de_passe) VALUES (?,?,?)",
            (nom, email, pwd)
        )
        db.commit()
        return jsonify({"success": True, "message": "Compte créé"})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "message": "Email déjà utilisé"}), 409

# ══════════════════════════════════════════════════════════════════════════════
# API — Médicaments / Stock
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/medicaments")
def get_medicaments():
    db = get_db()
    rows = db.execute("""
        SELECT *, 
        CASE 
            WHEN stock_actuel <= stock_minimum THEN 'critique'
            WHEN date_expiration <= date('now', '+60 days') THEN 'expiration'
            WHEN stock_actuel <= stock_minimum * 1.5 THEN 'bas'
            ELSE 'ok'
        END as etat
        FROM medicaments ORDER BY nom
    """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/medicaments", methods=["POST"])
def add_medicament():
    d = request.get_json()
    db = get_db()
    db.execute("""
        INSERT INTO medicaments (nom, categorie, unite, prix_achat, prix_vente,
        stock_actuel, stock_minimum, date_expiration, fournisseur)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (d["nom"], d.get("categorie",""), d.get("unite","boîte"),
          d.get("prix_achat",0), d.get("prix_vente",0),
          d.get("stock_actuel",0), d.get("stock_minimum",10),
          d.get("date_expiration",""), d.get("fournisseur","")))
    db.commit()
    return jsonify({"success": True})

@app.route("/api/medicaments/<int:mid>", methods=["PUT"])
def update_medicament(mid):
    d = request.get_json()
    db = get_db()
    db.execute("""
        UPDATE medicaments SET nom=?, categorie=?, prix_achat=?, prix_vente=?,
        stock_actuel=?, stock_minimum=?, date_expiration=?, fournisseur=?
        WHERE id=?
    """, (d["nom"], d.get("categorie",""), d.get("prix_achat",0),
          d.get("prix_vente",0), d.get("stock_actuel",0),
          d.get("stock_minimum",10), d.get("date_expiration",""),
          d.get("fournisseur",""), mid))
    db.commit()
    return jsonify({"success": True})

@app.route("/api/medicaments/<int:mid>", methods=["DELETE"])
def delete_medicament(mid):
    db = get_db()
    db.execute("DELETE FROM medicaments WHERE id=?", (mid,))
    db.commit()
    return jsonify({"success": True})

# ══════════════════════════════════════════════════════════════════════════════
# API — Ventes
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/ventes")
def get_ventes():
    db = get_db()
    rows = db.execute("""
        SELECT v.*, m.nom as medicament_nom
        FROM ventes v
        JOIN medicaments m ON v.medicament_id = m.id
        ORDER BY v.date_vente DESC LIMIT 200
    """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/ventes", methods=["POST"])
def add_vente():
    d = request.get_json()
    db = get_db()
    mid = d["medicament_id"]
    qty = int(d["quantite"])
    med = db.execute("SELECT prix_vente, stock_actuel FROM medicaments WHERE id=?", (mid,)).fetchone()
    if not med:
        return jsonify({"success": False, "message": "Médicament introuvable"}), 404
    prix = d.get("prix_unitaire", med["prix_vente"])
    db.execute("INSERT INTO ventes (medicament_id, quantite, prix_unitaire, total) VALUES (?,?,?,?)",
               (mid, qty, prix, prix * qty))
    db.execute("UPDATE medicaments SET stock_actuel = stock_actuel - ? WHERE id=?", (qty, mid))
    db.commit()
    return jsonify({"success": True})

# ══════════════════════════════════════════════════════════════════════════════
# API — Alertes
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/alertes")
def get_alertes():
    db = get_db()
    # Générer auto les alertes stock bas + expiration
    db.execute("DELETE FROM alertes WHERE type IN ('stock_bas','expiration') AND lue=0")
    # Stock bas
    bas = db.execute("""
        SELECT id, nom, stock_actuel, stock_minimum FROM medicaments
        WHERE stock_actuel <= stock_minimum AND statut='actif'
    """).fetchall()
    for m in bas:
        db.execute("INSERT INTO alertes (type, message, medicament_id, niveau) VALUES (?,?,?,?)",
                   ("stock_bas", f"Stock bas : {m['nom']} ({m['stock_actuel']} {'' if m['stock_actuel']>1 else ''}boîtes)", m["id"], "warning"))
    # Expiration < 60j
    exp = db.execute("""
        SELECT id, nom, date_expiration,
        CAST(julianday(date_expiration) - julianday('now') AS INTEGER) as jours
        FROM medicaments WHERE date_expiration != ''
        AND julianday(date_expiration) - julianday('now') BETWEEN 0 AND 60
        AND statut='actif'
    """).fetchall()
    for m in exp:
        niv = "danger" if m["jours"] < 30 else "warning"
        db.execute("INSERT INTO alertes (type, message, medicament_id, niveau) VALUES (?,?,?,?)",
                   ("expiration", f"Expiration dans {m['jours']}j : {m['nom']}", m["id"], niv))
    db.commit()
    rows = db.execute("SELECT * FROM alertes ORDER BY cree_le DESC LIMIT 50").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/alertes/<int:aid>/lue", methods=["PUT"])
def marquer_lue(aid):
    db = get_db()
    db.execute("UPDATE alertes SET lue=1 WHERE id=?", (aid,))
    db.commit()
    return jsonify({"success": True})

# ══════════════════════════════════════════════════════════════════════════════
# API — Stats / Dashboard
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/stats")
def get_stats():
    db = get_db()
    # Revenus ce mois
    revenu_mois = db.execute("""
        SELECT COALESCE(SUM(total),0) as total FROM ventes
        WHERE strftime('%Y-%m', date_vente) = strftime('%Y-%m', 'now')
    """).fetchone()["total"]
    # Revenus mois dernier
    revenu_precedent = db.execute("""
        SELECT COALESCE(SUM(total),0) as total FROM ventes
        WHERE strftime('%Y-%m', date_vente) = strftime('%Y-%m', date('now','-1 month'))
    """).fetchone()["total"]
    # Médicaments en stock bas
    stock_bas = db.execute("""
        SELECT COUNT(*) as n FROM medicaments WHERE stock_actuel <= stock_minimum AND statut='actif'
    """).fetchone()["n"]
    # Expirations < 60j
    expirations = db.execute("""
        SELECT COUNT(*) as n FROM medicaments
        WHERE date_expiration != '' AND julianday(date_expiration) - julianday('now') BETWEEN 0 AND 60
        AND statut='actif'
    """).fetchone()["n"]
    # Total médicaments
    total_meds = db.execute("SELECT COUNT(*) as n FROM medicaments WHERE statut='actif'").fetchone()["n"]
    # Ventes par mois (6 derniers mois)
    ventes_mois = db.execute("""
        SELECT strftime('%Y-%m', date_vente) as mois, SUM(total) as total, COUNT(*) as nb
        FROM ventes
        WHERE date_vente >= date('now', '-6 months')
        GROUP BY mois ORDER BY mois
    """).fetchall()
    # Top 5 médicaments vendus
    top_meds = db.execute("""
        SELECT m.nom, SUM(v.quantite) as qty_totale, SUM(v.total) as ca
        FROM ventes v JOIN medicaments m ON v.medicament_id = m.id
        WHERE v.date_vente >= date('now', '-30 days')
        GROUP BY v.medicament_id ORDER BY qty_totale DESC LIMIT 5
    """).fetchall()

    evolution = ((revenu_mois - revenu_precedent) / revenu_precedent * 100) if revenu_precedent > 0 else 0

    return jsonify({
        "revenu_mois": revenu_mois,
        "revenu_precedent": revenu_precedent,
        "evolution_pct": round(evolution, 1),
        "stock_bas": stock_bas,
        "expirations_proches": expirations,
        "total_medicaments": total_meds,
        "ventes_par_mois": [dict(r) for r in ventes_mois],
        "top_medicaments": [dict(r) for r in top_meds],
    })

# ══════════════════════════════════════════════════════════════════════════════
# API — Paramètres
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/parametres")
def get_parametres():
    db = get_db()
    rows = db.execute("SELECT * FROM parametres").fetchall()
    return jsonify({r["cle"]: r["valeur"] for r in rows})

@app.route("/api/parametres", methods=["PUT"])
def update_parametres():
    d = request.get_json()
    db = get_db()
    for cle, valeur in d.items():
        db.execute("UPDATE parametres SET valeur=?, modifie_le=datetime('now') WHERE cle=?",
                   (str(valeur), cle))
    db.commit()
    return jsonify({"success": True})

# ══════════════════════════════════════════════════════════════════════════════
# API — Utilisateurs (admin)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/utilisateurs")
def get_utilisateurs():
    db = get_db()
    rows = db.execute(
        "SELECT id, nom, email, role, plan, actif, cree_le FROM utilisateurs ORDER BY cree_le DESC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/utilisateurs/<int:uid>/toggle", methods=["PUT"])
def toggle_utilisateur(uid):
    db = get_db()
    db.execute("UPDATE utilisateurs SET actif = 1 - actif WHERE id=?", (uid,))
    db.commit()
    return jsonify({"success": True})

# ══════════════════════════════════════════════════════════════════════════════
# API — Liste d'achat IA
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/liste-achat")
def liste_achat():
    db = get_db()
    rows = db.execute("""
        SELECT m.*, 
        COALESCE((SELECT SUM(v.quantite) FROM ventes v WHERE v.medicament_id=m.id 
                  AND v.date_vente >= date('now','-30 days')),0) as ventes_30j,
        MAX(0, m.stock_minimum * 3 - m.stock_actuel) as qte_recommandee
        FROM medicaments m
        WHERE m.statut='actif' AND (m.stock_actuel <= m.stock_minimum * 2)
        ORDER BY (m.stock_minimum - m.stock_actuel) DESC
    """).fetchall()
    return jsonify([dict(r) for r in rows])

# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    print(f"✅ Base de données : {DB_PATH}")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
    
