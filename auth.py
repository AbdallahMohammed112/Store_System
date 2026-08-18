# هذا الملف مسئول عن نظام تسجيل الدخول، الخروج، وفحص الصلاحيات بشكل دقيق.

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import date
from database import get_db_conn

auth_bp = Blueprint('auth', __name__)

def get_entity():
    if session.get('role') == 'owner': 
        return 'all'
    if session.get('role') == 'admin': 
        return session.get('user_id')
    return session.get('parent_id')

def has_perm(module, action='v'):
    if 'username' not in session: 
        return False
    if session.get('role') == 'owner': 
        return True
    
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT p_{module}_{action} FROM users WHERE id=?", (session['user_id'],))
        res = cursor.fetchone()
        conn.close()
        return bool(res and res[0] == 1)
    except:
        conn.close()
        return False

# دالة مساعدة لتحويل نتائج SQLite لقاموس
def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

@auth_bp.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_conn()
        conn.row_factory = dict_factory
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        
        is_valid_password = False
        if user:
            if check_password_hash(user['password'], password):
                is_valid_password = True
            elif user['password'] == password: 
                is_valid_password = True
                hashed = generate_password_hash(password)
                cursor.execute("UPDATE users SET password=? WHERE id=?", (hashed, user['id']))
                conn.commit()
                
        if is_valid_password:
            user_status = user['status']
            user_expiry = user['expiry_date']
            
            if user['parent_id']:
                cursor.execute("SELECT status, expiry_date FROM users WHERE id=?", (user['parent_id'],))
                parent = cursor.fetchone()
                if parent:
                    if parent['status'] == 'suspended': 
                        user_status = 'suspended'
                    if parent['expiry_date'] and str(date.today()) > parent['expiry_date']: 
                        user_status = 'suspended'

            if user_status == 'suspended':
                conn.close()
                flash('الحساب موقوف، برجاء التواصل مع الإدارة.', 'error')
                return redirect(url_for('auth.login'))
            
            if user_expiry and str(date.today()) > user_expiry:
                cursor.execute("UPDATE users SET status='suspended' WHERE id=?", (user['id'],))
                conn.commit()
                conn.close()
                flash('انتهت فترة الاشتراك، برجاء التجديد.', 'error')
                return redirect(url_for('auth.login'))

            conn.close()
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['parent_id'] = user['parent_id']
            
            is_owner = (user['role'] == 'owner')
            
            # --- هذا هو الجزء الذي تمت إضافته لترجمة الصلاحيات للواجهة الأمامية ---
            modules = ['sales', 'prod', 'purch', 'exp', 'rep', 'part']
            actions = ['v', 'a', 'e', 'd']
            for mod in modules:
                for act in actions:
                    session[f'p_{mod}_{act}'] = 1 if is_owner else user[f'p_{mod}_{act}']
            
            session['view_cost'] = 'all' if is_owner else (user['view_cost'] if user['view_cost'] else 'none')
            session['view_scope'] = 'all' if is_owner else (user['view_scope'] if user['view_scope'] else 'own')
            session['pos_view'] = user.get('pos_view', 'desktop')
            # ----------------------------------------------------------------------
            
            return redirect(url_for('auth.dashboard'))
        else:
            conn.close()
            flash('اسم المستخدم أو كلمة المرور غير صحيحة!', 'error')
            
    return render_template('login.html')

@auth_bp.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('auth.login'))
        
    if has_perm('sales', 'v'): return redirect(url_for('sales.sales_page'))
    if has_perm('prod', 'v'): return redirect(url_for('products.products_page'))
    if has_perm('purch', 'v'): return redirect(url_for('purchases.purchases_page'))
    if has_perm('exp', 'v'): return redirect(url_for('expenses.expenses_page'))
    if has_perm('rep', 'v'): return redirect(url_for('reports.reports_page'))
    if has_perm('part', 'v'): return redirect(url_for('partners.partners_page'))
    if session.get('role') in ['owner', 'admin']: return redirect(url_for('settings.settings_page'))
    
    flash('لا تملك أي صلاحيات لعرض أي صفحة. تواصل مع الإدارة.', 'error')
    return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))