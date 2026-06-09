from flask import Flask, render_template, request, jsonify
import os

app = Flask(__name__, template_folder="templates")

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Landing page / onboarding."""
    return render_template("onboarding.html")


@app.route("/dashboard")
def dashboard():
    """Tableau de bord pharmacie."""
    return render_template("dashboard.html")


@app.route("/api/waitlist", methods=["POST"])
def waitlist():
    """
    Reçoit un email depuis le formulaire d'inscription.
    À brancher sur une base de données ou un service email (ex. Mailchimp).
    """
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()

    if not email or "@" not in email:
        return jsonify({"success": False, "message": "Adresse e-mail invalide."}), 400

    # TODO : enregistrer l'email en base ou envoyer vers Mailchimp / Brevo
    print(f"[Waitlist] Nouvel inscrit : {email}")

    return jsonify({"success": True, "message": "Bienvenue ! Accès au tableau de bord.", "redirect": "/dashboard"})


# ─── Lancement ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
    
