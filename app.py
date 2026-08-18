import os
import sqlite3
from flask import Flask, render_template, session, redirect, url_for
from database import init_db, init_settings_table, get_db_conn

from auth import auth_bp
from routes.sales import sales_bp
from routes.products import products_bp
from routes.partners import partners_bp
from routes.purchases import purchases_bp
from routes.expenses import expenses_bp
from routes.reports import reports_bp
from routes.settings import settings_bp

app = Flask(__name__)
app.secret_key = "super_erp_secret_key_2026"
app.config['UPLOAD_FOLDER'] = 'static/uploads'

os.makedirs('templates', exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

init_db()
init_settings_table()

@app.before_request
def refresh_permissions():
    if 'user_id' in session:
        conn = get_db_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id=?", (session['user_id'],))
        user = cursor.fetchone()
        
        if user:
            is_owner = (user['role'] == 'owner')
            modules = ['sales', 'prod', 'purch', 'exp', 'rep', 'part']
            actions = ['v', 'a', 'e', 'd']
            for mod in modules:
                for act in actions:
                    session[f'p_{mod}_{act}'] = 1 if is_owner else user[f"p_{mod}_{act}"]
            
            session['view_cost'] = 'all' if is_owner else (user['view_cost'] if user['view_cost'] else 'none')
            session['view_scope'] = 'all' if is_owner else (user['view_scope'] if user['view_scope'] else 'own')
            session['pos_view'] = user['pos_view'] if 'pos_view' in user.keys() else 'desktop'
            
            if is_owner:
                session['allow_mobile_pos'] = 1
            else:
                if user['role'] == 'admin':
                    session['allow_mobile_pos'] = user['allow_mobile_pos'] if 'allow_mobile_pos' in user.keys() else 0
                else:
                    cursor.execute("SELECT allow_mobile_pos FROM users WHERE id=?", (user['parent_id'],))
                    parent = cursor.fetchone()
                    session['allow_mobile_pos'] = parent['allow_mobile_pos'] if parent and 'allow_mobile_pos' in parent.keys() else 0
        conn.close()

app.register_blueprint(auth_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(products_bp)
app.register_blueprint(partners_bp)
app.register_blueprint(purchases_bp)
app.register_blueprint(expenses_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(settings_bp)

@app.route('/contact')
def contact():
    if 'username' not in session:
        return redirect(url_for('auth.login'))
    return render_template('contact.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)