import os
import json
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file, after_this_request
import sqlite3
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "super_erp_secret_key_2026"

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def ensure_dirs_exist():
    if not os.path.exists('templates'):
        os.makedirs('templates')
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

ensure_dirs_exist()

# ==========================================
# الاتصال بقاعدة البيانات (مع تفعيل WAL لمنع التهنيج)
# ==========================================
def get_db_conn():
    conn = sqlite3.connect('store_db.sqlite', timeout=20)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    conn = get_db_conn()
    cursor = conn.cursor()
    
    # جدول المستخدمين
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        username TEXT NOT NULL, 
                        password TEXT NOT NULL, 
                        role TEXT DEFAULT 'admin'
                    )''')
    
    # مصفوفة الصلاحيات
    modules = ['sales', 'prod', 'purch', 'exp', 'rep', 'part']
    actions = ['v', 'a', 'e', 'd']
    for mod in modules:
        for act in actions:
            try: 
                cursor.execute(f"ALTER TABLE users ADD COLUMN p_{mod}_{act} INTEGER DEFAULT 0")
            except sqlite3.OperationalError: 
                pass

    # إعدادات الـ SaaS
    columns_to_add = [
        ("parent_id", "INTEGER"),
        ("view_cost", "TEXT DEFAULT 'all'"),
        ("view_scope", "TEXT DEFAULT 'own'"),
        ("status", "TEXT DEFAULT 'active'"),
        ("expiry_date", "DATE"),
        ("max_users", "INTEGER DEFAULT 0")
    ]
    for col_name, col_type in columns_to_add:
        try: 
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError: 
            pass

    def add_entity_col(table):
        try: 
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN entity_id INTEGER DEFAULT 1")
        except sqlite3.OperationalError: 
            pass

    # الجداول الأساسية
    cursor.execute('''CREATE TABLE IF NOT EXISTS products (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        name TEXT NOT NULL, 
                        cost_price REAL NOT NULL, 
                        sell_price REAL NOT NULL, 
                        stock_qty INTEGER NOT NULL
                    )''')
    try: cursor.execute("ALTER TABLE products ADD COLUMN partner_name TEXT DEFAULT 'بدون شريك'")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE products ADD COLUMN created_by TEXT")
    except sqlite3.OperationalError: pass
    add_entity_col('products')

    cursor.execute('''CREATE TABLE IF NOT EXISTS partners (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        name TEXT NOT NULL, 
                        phone TEXT
                    )''')
    try: cursor.execute("ALTER TABLE partners ADD COLUMN profit_share REAL DEFAULT 100")
    except sqlite3.OperationalError: pass
    add_entity_col('partners')

    cursor.execute('''CREATE TABLE IF NOT EXISTS partner_withdrawals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        partner_id INTEGER, 
                        amount REAL, 
                        notes TEXT, 
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')
    add_entity_col('partner_withdrawals')

    cursor.execute('''CREATE TABLE IF NOT EXISTS invoices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        invoice_no TEXT NOT NULL, 
                        customer_name TEXT, 
                        customer_phone TEXT, 
                        total_amount REAL NOT NULL, 
                        total_profit REAL NOT NULL, 
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')
    try: cursor.execute("ALTER TABLE invoices ADD COLUMN created_by TEXT DEFAULT 'admin'")
    except sqlite3.OperationalError: pass
    add_entity_col('invoices')

    cursor.execute('''CREATE TABLE IF NOT EXISTS invoice_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        invoice_no TEXT NOT NULL, 
                        product_id INTEGER, 
                        product_name TEXT, 
                        qty INTEGER, 
                        sell_price REAL, 
                        partner_name TEXT, 
                        profit REAL
                    )''')
    add_entity_col('invoice_items')

    cursor.execute('''CREATE TABLE IF NOT EXISTS purchases (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        supplier_name TEXT, 
                        total_amount REAL NOT NULL, 
                        status TEXT DEFAULT 'pending', 
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')
    add_entity_col('purchases')

    cursor.execute('''CREATE TABLE IF NOT EXISTS purchase_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        purchase_id INTEGER, 
                        product_id INTEGER, 
                        product_name TEXT, 
                        qty INTEGER, 
                        cost_price REAL, 
                        partner_name TEXT, 
                        total REAL
                    )''')
    try: cursor.execute("ALTER TABLE purchase_items ADD COLUMN partner_name TEXT")
    except sqlite3.OperationalError: pass
    add_entity_col('purchase_items')

    cursor.execute('''CREATE TABLE IF NOT EXISTS expenses (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        amount REAL NOT NULL, 
                        category TEXT NOT NULL, 
                        notes TEXT, 
                        created_by TEXT,
                        expense_date DATE DEFAULT (date('now','localtime')), 
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')
    add_entity_col('expenses')
    
    # إنشاء المالك المطلق بتشفير الباسورد
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        hashed_pw = generate_password_hash('123')
        cursor.execute('''INSERT INTO users (
                            username, password, role, view_cost, view_scope, status, max_users, 
                            p_sales_v, p_sales_a, p_sales_e, p_sales_d, 
                            p_prod_v, p_prod_a, p_prod_e, p_prod_d, 
                            p_purch_v, p_purch_a, p_purch_e, p_purch_d, 
                            p_exp_v, p_exp_a, p_exp_e, p_exp_d, 
                            p_rep_v, p_rep_a, p_rep_e, p_rep_d, 
                            p_part_v, p_part_a, p_part_e, p_part_d
                          ) VALUES (
                            'admin', ?, 'owner', 'all', 'all', 'active', 999, 
                            1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,1
                          )''', (hashed_pw,))
    conn.commit()
    conn.close()

def init_settings_table():
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS store_settings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        entity_id INTEGER DEFAULT 1, 
                        store_name TEXT, 
                        store_phone TEXT, 
                        store_branch TEXT, 
                        invoice_footer TEXT
                    )''')
    try: 
        cursor.execute("ALTER TABLE store_settings ADD COLUMN logo TEXT")
    except sqlite3.OperationalError: 
        pass
        
    cursor.execute("SELECT COUNT(*) FROM store_settings WHERE entity_id=1")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''INSERT INTO store_settings (entity_id, store_name, store_phone, store_branch, invoice_footer) 
                          VALUES (1, 'نظام المتجر الذكي', '01012345678', 'الفرع الرئيسي', 'شكراً لزيارتكم!')''')
    conn.commit()
    conn.close()

init_db()
init_settings_table()

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
    return session.get(f'p_{module}_{action}') == 1

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    if has_perm('sales', 'v'): return redirect(url_for('sales'))
    if has_perm('prod', 'v'): return redirect(url_for('products'))
    if has_perm('purch', 'v'): return redirect(url_for('purchases'))
    if has_perm('exp', 'v'): return redirect(url_for('expenses'))
    if has_perm('rep', 'v'): return redirect(url_for('reports'))
    if has_perm('part', 'v'): return redirect(url_for('partners'))
    if session.get('role') in ['owner', 'admin']: return redirect(url_for('settings'))
    
    flash('لا تملك أي صلاحيات لعرض أي صفحة. تواصل مع الإدارة.', 'error')
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        
        is_valid_password = False
        if user:
            if check_password_hash(user['password'], password):
                is_valid_password = True
            elif user['password'] == password: # توافق مع الباسورد القديم الغير مشفر
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
                return redirect(url_for('login'))
            
            if user_expiry and str(date.today()) > user_expiry:
                cursor.execute("UPDATE users SET status='suspended' WHERE id=?", (user['id'],))
                conn.commit()
                conn.close()
                flash('انتهت فترة الاشتراك، برجاء التجديد.', 'error')
                return redirect(url_for('login'))

            conn.close()
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['parent_id'] = user['parent_id']
            is_owner = (user['role'] == 'owner')
            
            modules = ['sales', 'prod', 'purch', 'exp', 'rep', 'part']
            actions = ['v', 'a', 'e', 'd']
            for mod in modules:
                for act in actions:
                    session[f'p_{mod}_{act}'] = 1 if is_owner else user[f'p_{mod}_{act}']
                    
            session['view_cost'] = 'all' if is_owner else (user['view_cost'] if user['view_cost'] else 'none')
            session['view_scope'] = 'all' if is_owner else (user['view_scope'] if user['view_scope'] else 'own')
            
            return redirect(url_for('dashboard'))
        else:
            conn.close()
            flash('اسم المستخدم أو كلمة المرور غير صحيحة!', 'error')
            
    return render_template('login.html')
@app.route('/sales')
def sales():
    if not has_perm('sales', 'v'):
        flash('غير مصرح لك بدخول نقطة البيع!', 'error')
        return redirect(url_for('dashboard'))
        
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row  
    cursor = conn.cursor()
    entity = get_entity()
    current_user = session.get('username')
    
    can_view_all_products = (session.get('view_scope') == 'all' or session.get('role') in ['owner', 'admin'])
    can_view_cost = (session.get('view_cost') == 'all' or session.get('role') in ['owner', 'admin'])
    
    if entity == 'all':
        cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name FROM products WHERE stock_qty > 0")
        raw_products = cursor.fetchall()
        cursor.execute("SELECT * FROM partners")
        partners = cursor.fetchall()
        cursor.execute("SELECT store_name, store_phone, store_branch, invoice_footer, logo FROM store_settings LIMIT 1")
        st_row = cursor.fetchone()
    else:
        if can_view_all_products:
            cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name FROM products WHERE stock_qty > 0 AND (entity_id=? OR 1=1)", (entity,))
        else:
            cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name FROM products WHERE stock_qty > 0 AND entity_id=? AND created_by=?", (entity, current_user))
            
        raw_products = cursor.fetchall()
        cursor.execute("SELECT * FROM partners WHERE entity_id=?", (entity,))
        partners = cursor.fetchall()
        cursor.execute("SELECT store_name, store_phone, store_branch, invoice_footer, logo FROM store_settings WHERE entity_id=? LIMIT 1", (entity,))
        st_row = cursor.fetchone()
        
    available_products = []
    for p in raw_products:
        p_dict = dict(p)
        if not can_view_cost:
            p_dict['cost_price'] = 0.0
        available_products.append(p_dict)
        
    store_info = {
        'name': st_row['store_name'] if st_row else 'المتجر',
        'phone': st_row['store_phone'] if st_row else '',
        'branch': st_row['store_branch'] if st_row else '',
        'footer': st_row['invoice_footer'] if st_row else '',
        'logo': st_row['logo'] if st_row and 'logo' in st_row.keys() else None
    }
    
    conn.close()
    return render_template('sales.html', products=available_products, partners=partners, store=store_info)

@app.route('/print_receipt', methods=['POST'])
def print_receipt():
    if not has_perm('sales', 'a'): 
        return "غير مصرح لك بإصدار فواتير", 403
        
    data = request.json
    if not data: 
        return "بيانات غير صالحة", 400

    customer_name = data.get('customer_name', 'عميل نقدي')
    items = data.get('items', [])
    subtotal = float(data.get('subtotal', 0))
    discount = float(data.get('discount', 0))
    net_total = float(data.get('net_total', 0))
    allow_negative = data.get('allow_negative', False)
    
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    cursor.execute("SELECT store_name, store_phone, store_branch, invoice_footer, logo FROM store_settings WHERE entity_id=? LIMIT 1", (real_entity,))
    st_row = cursor.fetchone()
    store_info = {
        'name': st_row[0] if st_row else 'المتجر', 
        'phone': st_row[1] if st_row else '', 
        'branch': st_row[2] if st_row else '', 
        'footer': st_row[3] if st_row else '',
        'logo': st_row[4] if st_row and len(st_row) > 4 else None
    }
    
    if not allow_negative:
        for item in items:
            prod_id = item.get('id')
            qty = int(item.get('qty', 1))
            if prod_id:
                if entity == 'all': 
                    cursor.execute("SELECT stock_qty, name FROM products WHERE id=?", (prod_id,))
                else: 
                    cursor.execute("SELECT stock_qty, name FROM products WHERE id=? AND entity_id=?", (prod_id, entity))
                    
                res = cursor.fetchone()
                if res and res[0] < qty:
                    conn.close()
                    return f"الكمية المتوفرة من المنتج ({res[1]}) هي ({res[0]}) فقط!", 400

    total_invoice_profit = 0
    if entity == 'all': 
        cursor.execute("SELECT MAX(CAST(invoice_no AS INTEGER)) FROM invoices")
    else: 
        cursor.execute("SELECT MAX(CAST(invoice_no AS INTEGER)) FROM invoices WHERE entity_id=?", (entity,))
        
    max_inv = cursor.fetchone()[0]
    invoice_no = str((max_inv or 10000) + 1)
    current_user = session.get('username', 'غير معروف')

    for item in items:
        prod_id = item.get('id')
        qty = int(item.get('qty', 1))
        sell_price = float(item.get('price', 0))
        partner_name = item.get('partner', 'بدون شريك')
        cost_price = float(item.get('cost_price', 0))
        
        if prod_id:
            cursor.execute("SELECT cost_price, partner_name FROM products WHERE id=?", (prod_id,))
            res = cursor.fetchone()
            if res: 
                cost_price = float(res[0])
                if not partner_name or partner_name == 'بدون شريك': 
                    partner_name = res[1] or 'بدون شريك'
        
        item_profit = (sell_price - cost_price) * qty
        total_invoice_profit += item_profit

        cursor.execute('''INSERT INTO invoice_items (
                            invoice_no, product_id, product_name, qty, sell_price, partner_name, profit, entity_id
                          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                       (invoice_no, prod_id, item.get('name'), qty, sell_price, partner_name, item_profit, real_entity))
                
        if prod_id:
            if allow_negative: 
                cursor.execute("UPDATE products SET stock_qty = MAX(0, stock_qty - ?) WHERE id=?", (qty, prod_id))
            else: 
                cursor.execute("UPDATE products SET stock_qty = stock_qty - ? WHERE id=?", (qty, prod_id))

    cursor.execute('''INSERT INTO invoices (
                        invoice_no, customer_name, total_amount, total_profit, created_by, entity_id
                      ) VALUES (?, ?, ?, ?, ?, ?)''', 
                   (invoice_no, customer_name, net_total, total_invoice_profit, current_user, real_entity))
                   
    conn.commit()
    conn.close()
    
    return render_template('print_invoice.html', customer_name=customer_name, items=items, subtotal=f"{subtotal:.2f}", discount=f"{discount:.2f}", net_total=f"{net_total:.2f}", date=datetime.now().strftime('%Y-%m-%d'), invoice_no=invoice_no, store=store_info, cashier=current_user)

@app.route('/products', methods=['GET', 'POST'])
def products():
    if not has_perm('prod', 'v'):
        flash('غير مصرح لك بعرض المنتجات!', 'error')
        return redirect(url_for('dashboard'))
        
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    current_user = session.get('username')
    
    can_view_all_products = (session.get('view_scope') == 'all' or session.get('role') in ['owner', 'admin'])
    can_view_cost = (session.get('view_cost') == 'all' or session.get('role') in ['owner', 'admin'])
    
    if request.method == 'POST':
        if not has_perm('prod', 'a'): 
            return redirect(url_for('products'))
            
        name = request.form.get('name', 'بدون اسم')
        partner_name = request.form.get('partner_name', 'بدون شريك')
        
        sell_price_str = request.form.get('sell_price', '0')
        stock_qty_str = request.form.get('stock_qty', '0')
        cost_price_str = request.form.get('cost_price', '0')
            
        sell_price = float(sell_price_str) if sell_price_str.strip() else 0.0
        cost_price = float(cost_price_str) if cost_price_str.strip() else 0.0
        stock_qty = int(stock_qty_str) if stock_qty_str.strip() else 0
        
        try:
            cursor.execute('''INSERT INTO products (
                                name, cost_price, sell_price, stock_qty, partner_name, created_by, entity_id
                              ) VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                           (name, cost_price, sell_price, stock_qty, partner_name, current_user, real_entity))
            conn.commit()
        except Exception as e:
            print(f"Error: {e}")
            
        conn.close()
        return redirect(url_for('products'))
    
    if entity == 'all':
        cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name, created_by FROM products ORDER BY id DESC")
        raw_products = cursor.fetchall()
        cursor.execute("SELECT * FROM partners")
        partners_list = cursor.fetchall()
    else:
        if can_view_all_products:
            cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name, created_by FROM products WHERE entity_id=? ORDER BY id DESC", (entity,))
        else:
            cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name, created_by FROM products WHERE entity_id=? AND created_by=? ORDER BY id DESC", (entity, current_user))
            
        raw_products = cursor.fetchall()
        cursor.execute("SELECT * FROM partners WHERE entity_id=?", (entity,))
        partners_list = cursor.fetchall()
        
    all_products = []
    for p in raw_products:
        p_dict = dict(p)
        if not can_view_cost:
            p_dict['cost_price'] = 0.0
        all_products.append(p_dict)
        
    conn.close()
    return render_template('products.html', products=all_products, partners=partners_list)

@app.route('/delete_product/<int:id>')
def delete_product(id):
    if not has_perm('prod', 'd'): 
        return redirect(url_for('products'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('products'))

@app.route('/edit_product', methods=['POST'])
def edit_product():
    if not has_perm('prod', 'e'): 
        return redirect(url_for('products'))
        
    prod_id = int(request.form.get('prod_id', '0'))
    name = request.form.get('name', 'بدون اسم')
    sell_price = float(request.form.get('sell_price', '0') or 0.0)
    stock_qty = int(request.form.get('stock_qty', '0') or 0)
    partner_name = request.form.get('partner_name', 'بدون شريك')
    
    conn = get_db_conn()
    cursor = conn.cursor()
    
    if session.get('view_cost') == 'all' or session.get('role') in ['owner', 'admin']:
        cost_price = float(request.form.get('cost_price', '0') or 0.0)
    else:
        cursor.execute("SELECT cost_price FROM products WHERE id=?", (prod_id,))
        res = cursor.fetchone()
        cost_price = res[0] if res else 0.0

    try:
        cursor.execute('''UPDATE products SET name=?, cost_price=?, sell_price=?, stock_qty=?, partner_name=? WHERE id=?''', 
                       (name, cost_price, sell_price, stock_qty, partner_name, prod_id))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
        
    conn.close()
    return redirect(url_for('products'))

def parse_profit_share(val_str):
    try:
        val_str = str(val_str).strip()
        if '/' in val_str:
            parts = val_str.split('/')
            if len(parts) == 2 and float(parts[1]) != 0:
                return (float(parts[0]) / float(parts[1])) * 100
        return float(val_str)
    except Exception: 
        return 100.0

@app.route('/add_withdrawal', methods=['POST'])
def add_withdrawal():
    if not has_perm('part', 'a'): 
        return redirect(url_for('partners'))
        
    partner_id = request.form['partner_id']
    amount = float(request.form['amount'])
    notes = request.form.get('notes', '')
    allow_negative = True if request.form.get('allow_negative') == 'on' else False
    
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    cursor.execute("SELECT name, profit_share FROM partners WHERE id=?", (partner_id,))
    p_data = cursor.fetchone()
    if not p_data:
        conn.close()
        return redirect(url_for('partners'))
        
    partner_name = p_data[0]
    profit_share = p_data[1] or 100.0
    
    if entity == 'all': 
        cursor.execute("SELECT SUM(profit) FROM invoice_items WHERE partner_name=?", (partner_name,))
    else: 
        cursor.execute("SELECT SUM(profit) FROM invoice_items WHERE partner_name=? AND entity_id=?", (partner_name, entity))
        
    tot_profit_res = cursor.fetchone()[0]
    tot_profit = tot_profit_res if tot_profit_res is not None else 0.0
    net_partner_profit = tot_profit * (profit_share / 100.0)
    
    cursor.execute("SELECT SUM(amount) FROM partner_withdrawals WHERE partner_id=?", (partner_id,))
    total_withdrawn_res = cursor.fetchone()[0]
    total_withdrawn = total_withdrawn_res if total_withdrawn_res is not None else 0.0
    net_due = net_partner_profit - total_withdrawn
    
    if amount > net_due and not allow_negative:
        conn.close()
        flash(f'المبلغ المطلوب أكبر من الأرباح المتاحة ({net_due:.2f}).', 'error')
        return redirect(url_for('partners'))

    cursor.execute("INSERT INTO partner_withdrawals (partner_id, amount, notes, entity_id) VALUES (?, ?, ?, ?)", 
                   (partner_id, amount, notes, real_entity))
    conn.commit()
    conn.close()
    flash('تم تسجيل تسليم الأرباح بنجاح!', 'success')
    return redirect(url_for('partners'))

@app.route('/edit_withdrawal', methods=['POST'])
def edit_withdrawal():
    if not has_perm('part', 'e'): 
        return redirect(url_for('partners'))
        
    withdrawal_id = request.form['withdrawal_id']
    amount = float(request.form['amount'])
    notes = request.form.get('notes', '')
    
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE partner_withdrawals SET amount=?, notes=? WHERE id=?", (amount, notes, withdrawal_id))
    conn.commit()
    conn.close()
    flash('تم التعديل!', 'success')
    return redirect(url_for('partners'))

@app.route('/delete_withdrawal/<int:withdrawal_id>')
def delete_withdrawal(withdrawal_id):
    if not has_perm('part', 'd'): 
        return redirect(url_for('partners'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM partner_withdrawals WHERE id=?", (withdrawal_id,))
    conn.commit()
    conn.close()
    flash('تم حذف عملية السحب.', 'success')
    return redirect(url_for('partners'))

@app.route('/partners', methods=['GET', 'POST'])
def partners():
    if not has_perm('part', 'v'):
        flash('غير مصرح لك بالوصول لصفحة الشركاء!', 'error')
        return redirect(url_for('dashboard'))
    
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    if request.method == 'POST':
        if not has_perm('part', 'a'): 
            return redirect(url_for('partners'))
            
        name = request.form['name']
        phone = request.form['phone']
        profit_share = parse_profit_share(request.form.get('profit_share', '100'))
        
        cursor.execute("INSERT INTO partners (name, phone, profit_share, entity_id) VALUES (?, ?, ?, ?)", 
                       (name, phone, profit_share, real_entity))
        conn.commit()
        conn.close()
        return redirect(url_for('partners'))
    
    date_from_str = request.args.get('date_from', '').strip()
    date_to_str = request.args.get('date_to', '').strip()
    d_from = datetime.strptime(date_from_str, '%Y-%m-%d').date() if date_from_str else None
    d_to = datetime.strptime(date_to_str, '%Y-%m-%d').date() if date_to_str else None
    
    if entity == 'all': 
        cursor.execute("SELECT * FROM partners")
    else: 
        cursor.execute("SELECT * FROM partners WHERE entity_id=?", (entity,))
        
    partners_list = cursor.fetchall()
    
    partner_stats = {}
    partner_transactions = {}
    
    for p in partners_list:
        partner_id = p[0]
        partner_name = p[1]
        profit_share = p[3] if len(p) > 3 and p[3] is not None else 100.0
        
        if entity == 'all':
            cursor.execute('''SELECT ii.product_name, ii.qty, ii.sell_price, (ii.sell_price * ii.qty), ii.profit, 
                              i.created_at, i.invoice_no, i.customer_name 
                              FROM invoice_items ii 
                              JOIN invoices i ON ii.invoice_no = i.invoice_no 
                              WHERE ii.partner_name = ? ORDER BY i.created_at DESC, ii.id DESC''', (partner_name,))
        else:
            cursor.execute('''SELECT ii.product_name, ii.qty, ii.sell_price, (ii.sell_price * ii.qty), ii.profit, 
                              i.created_at, i.invoice_no, i.customer_name 
                              FROM invoice_items ii 
                              JOIN invoices i ON ii.invoice_no = i.invoice_no 
                              WHERE ii.partner_name = ? AND ii.entity_id = ? 
                              ORDER BY i.created_at DESC, ii.id DESC''', (partner_name, entity))
        rows = cursor.fetchall()
        
        transactions = []
        tot_sales = 0.0
        tot_profit = 0.0
        tot_qty = 0
        
        for r in rows:
            try: 
                inv_date = datetime.strptime(r[5][:10], '%Y-%m-%d').date()
            except Exception: 
                continue
                
            if d_from and inv_date < d_from: continue
            if d_to and inv_date > d_to: continue
                
            transactions.append({
                'date': r[5], 'invoice_no': r[6], 'customer': r[7] or 'عميل نقدي', 
                'product': r[0], 'qty': r[1] or 0, 'price': r[2] or 0.0, 
                'total_sale': r[3] or 0.0, 'profit': r[4] or 0.0
            })
            tot_sales += (r[3] or 0.0)
            tot_profit += (r[4] or 0.0)
            tot_qty += (r[1] or 0)
            
        net_partner_profit = tot_profit * (profit_share / 100.0)
        cursor.execute("SELECT SUM(amount) FROM partner_withdrawals WHERE partner_id=?", (partner_id,))
        total_withdrawn_res = cursor.fetchone()[0]
        total_withdrawn = total_withdrawn_res if total_withdrawn_res is not None else 0.0
        
        cursor.execute("SELECT id, amount, notes, created_at FROM partner_withdrawals WHERE partner_id=? ORDER BY created_at DESC", (partner_id,))
        withdrawals_rows = cursor.fetchall()
        net_due = net_partner_profit - total_withdrawn
        
        partner_stats[partner_name] = {
            'sales': tot_sales, 
            'total_profit': tot_profit, 
            'partner_profit': net_partner_profit, 
            'total_withdrawn': total_withdrawn, 
            'withdrawals': withdrawals_rows, 
            'net_due': net_due, 
            'count': tot_qty, 
            'share': profit_share
        }
        partner_transactions[partner_name] = transactions
        
    conn.close()
    return render_template('partners.html', partners=partners_list, stats=partner_stats, partner_transactions=partner_transactions, date_from=date_from_str, date_to=date_to_str)

@app.route('/edit_partner', methods=['POST'])
def edit_partner():
    if not has_perm('part', 'e'): 
        return redirect(url_for('partners'))
        
    partner_id = request.form['partner_id']
    new_name = request.form['name']
    new_phone = request.form['phone']
    new_share = parse_profit_share(request.form.get('profit_share', '100'))
    
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM partners WHERE id=?", (partner_id,))
    old_name = cursor.fetchone()[0]
    
    cursor.execute("UPDATE partners SET name=?, phone=?, profit_share=? WHERE id=?", 
                   (new_name, new_phone, new_share, partner_id))
                   
    if old_name != new_name:
        cursor.execute("UPDATE invoice_items SET partner_name=? WHERE partner_name=?", (new_name, old_name))
        cursor.execute("UPDATE purchase_items SET partner_name=? WHERE partner_name=?", (new_name, old_name))
        cursor.execute("UPDATE products SET partner_name=? WHERE partner_name=?", (new_name, old_name))
        
    conn.commit()
    conn.close()
    return redirect(url_for('partners'))

@app.route('/delete_partner/<int:id>')
def delete_partner(id):
    if not has_perm('part', 'd'): 
        return redirect(url_for('partners'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM partners WHERE id=?", (id,))
    partner_row = cursor.fetchone()
    
    if partner_row:
        partner_name = partner_row[0]
        cursor.execute("UPDATE invoice_items SET partner_name='بدون شريك' WHERE partner_name=?", (partner_name,))
        cursor.execute("UPDATE purchase_items SET partner_name='بدون شريك' WHERE partner_name=?", (partner_name,))
        cursor.execute("UPDATE products SET partner_name='بدون شريك' WHERE partner_name=?", (partner_name,))
        cursor.execute("DELETE FROM partner_withdrawals WHERE partner_id=?", (id,))
        
    cursor.execute("DELETE FROM partners WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('partners'))

@app.route('/purchases')
def purchases():
    if not has_perm('purch', 'v'):
        flash('غير مصرح لك بالدخول للمشتريات!', 'error')
        return redirect(url_for('dashboard'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    
    if entity == 'all':
        cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name FROM products ORDER BY name ASC")
        products_list = cursor.fetchall()
        cursor.execute("SELECT * FROM partners")
        partners_list = cursor.fetchall()
        cursor.execute("SELECT id, supplier_name, total_amount, created_at, status FROM purchases ORDER BY id DESC LIMIT 25")
        purchases_history = cursor.fetchall()
    else:
        cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name FROM products WHERE entity_id=? ORDER BY name ASC", (entity,))
        products_list = cursor.fetchall()
        cursor.execute("SELECT * FROM partners WHERE entity_id=?", (entity,))
        partners_list = cursor.fetchall()
        cursor.execute("SELECT id, supplier_name, total_amount, created_at, status FROM purchases WHERE entity_id=? ORDER BY id DESC LIMIT 25", (entity,))
        purchases_history = cursor.fetchall()
        
    conn.close()
    return render_template('purchases.html', products=products_list, partners=partners_list, purchases=purchases_history)

@app.route('/save_purchase', methods=['POST'])
def save_purchase():
    if not has_perm('purch', 'a'): 
        return jsonify({"error": "Unauthorized"}), 403
        
    data = request.json
    if not data: 
        return jsonify({"error": "بيانات غير صالحة"}), 400
    
    supplier_name = data.get('supplier_name', 'مورد عام')
    items = data.get('items', [])
    total_amount = float(data.get('total_amount', 0))
    if not items: 
        return jsonify({"error": "قائمة المشتريات فارغة!"}), 400
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    cursor.execute("INSERT INTO purchases (supplier_name, total_amount, status, entity_id) VALUES (?, ?, 'pending', ?)", 
                   (supplier_name, total_amount, real_entity))
    purchase_id = cursor.lastrowid
    
    for item in items:
        prod_id = item.get('id')
        prod_name = item.get('name')
        qty = int(item.get('qty', 0))
        cost_price = float(item.get('cost_price', 0))
        partner_name = item.get('partner', 'بدون شريك')
        item_total = qty * cost_price
        
        cursor.execute('''INSERT INTO purchase_items (
                            purchase_id, product_id, product_name, qty, cost_price, partner_name, total, entity_id
                          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                       (purchase_id, prod_id, prod_name, qty, cost_price, partner_name, item_total, real_entity))
        
    conn.commit()
    conn.close()
    return jsonify({"message": "تم تسجيل الفاتورة كمسودة!", "purchase_id": purchase_id})

@app.route('/review_purchase/<int:purchase_id>')
def review_purchase(purchase_id):
    if not has_perm('purch', 'v'): 
        return redirect(url_for('dashboard'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    
    if entity == 'all':
        cursor.execute("SELECT id, supplier_name, total_amount, created_at, status FROM purchases WHERE id=?", (purchase_id,))
        purchase = cursor.fetchone()
        cursor.execute("SELECT id, product_id, product_name, qty, cost_price, partner_name FROM purchase_items WHERE purchase_id=?", (purchase_id,))
        items = cursor.fetchall()
        cursor.execute("SELECT * FROM partners")
        partners = cursor.fetchall()
    else:
        cursor.execute("SELECT id, supplier_name, total_amount, created_at, status FROM purchases WHERE id=? AND entity_id=?", (purchase_id, entity))
        purchase = cursor.fetchone()
        cursor.execute("SELECT id, product_id, product_name, qty, cost_price, partner_name FROM purchase_items WHERE purchase_id=? AND entity_id=?", (purchase_id, entity))
        items = cursor.fetchall()
        cursor.execute("SELECT * FROM partners WHERE entity_id=?", (entity,))
        partners = cursor.fetchall()
        
    if not purchase: 
        conn.close()
        return "الفاتورة غير موجودة!", 404
        
    conn.close()
    return render_template('review_purchase.html', purchase=purchase, items=items, partners=partners)

@app.route('/commit_purchase/<int:purchase_id>', methods=['POST'])
def commit_purchase(purchase_id):
    if not has_perm('purch', 'e'): 
        return redirect(url_for('dashboard'))
        
    data = request.json
    pricing_items = data.get('items', [])
    
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    for item in pricing_items:
        p_item_id = item['item_id']
        sell_price = float(item['sell_price'])
        new_partner = item['partner']
        
        cursor.execute("SELECT product_id, product_name, qty, cost_price, partner_name FROM purchase_items WHERE id=?", (p_item_id,))
        p_item = cursor.fetchone()
        
        if p_item:
            prod_id, prod_name, qty, cost_price, p_name = p_item
            if not prod_id:
                if entity == 'all': 
                    cursor.execute("SELECT id FROM products WHERE name=?", (prod_name,))
                else: 
                    cursor.execute("SELECT id FROM products WHERE name=? AND entity_id=?", (prod_name, entity))
                
                res = cursor.fetchone()
                if res: 
                    prod_id = res[0]
                else:
                    cursor.execute('''INSERT INTO products (
                                        name, cost_price, sell_price, stock_qty, partner_name, created_by, entity_id
                                      ) VALUES (?, ?, ?, 0, ?, ?, ?)''', 
                                   (prod_name, cost_price, sell_price, new_partner, session['username'], real_entity))
                    prod_id = cursor.lastrowid
                    
            cursor.execute("UPDATE purchase_items SET product_id=?, partner_name=? WHERE id=?", (prod_id, new_partner, p_item_id))
            cursor.execute("UPDATE products SET stock_qty = stock_qty + ?, cost_price = ?, sell_price = ?, partner_name = ? WHERE id = ?", (qty, cost_price, sell_price, new_partner, prod_id))
            
    cursor.execute("UPDATE purchases SET status='completed' WHERE id=?", (purchase_id,))
    conn.commit()
    conn.close()
    return "تم تسعير وترحيل المنتجات للمخزن بنجاح!"

@app.route('/view_purchase/<int:purchase_id>')
def view_purchase(purchase_id):
    if not has_perm('purch', 'v'): 
        return redirect(url_for('dashboard'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    
    if entity == 'all':
        cursor.execute("SELECT id, supplier_name, total_amount, created_at FROM purchases WHERE id=?", (purchase_id,))
        purchase = cursor.fetchone()
        cursor.execute("SELECT product_name, qty, cost_price, partner_name, total FROM purchase_items WHERE purchase_id=?", (purchase_id,))
        items = cursor.fetchall()
    else:
        cursor.execute("SELECT id, supplier_name, total_amount, created_at FROM purchases WHERE id=? AND entity_id=?", (purchase_id, entity))
        purchase = cursor.fetchone()
        cursor.execute("SELECT product_name, qty, cost_price, partner_name, total FROM purchase_items WHERE purchase_id=? AND entity_id=?", (purchase_id, entity))
        items = cursor.fetchall()
        
    conn.close()
    if not purchase: 
        return "الفاتورة غير موجودة!", 404
        
    return render_template('print_purchase.html', purchase=purchase, items=items)

@app.route('/expenses', methods=['GET', 'POST'])
def expenses():
    if not has_perm('exp', 'v'):
        flash('غير مصرح لك بإدارة المصروفات!', 'error')
        return redirect(url_for('dashboard'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    if request.method == 'POST':
        if not has_perm('exp', 'a'): 
            return redirect(url_for('expenses'))
            
        amount = request.form.get('amount')
        category = request.form.get('category')
        notes = request.form.get('notes', '')
        date_val = request.form.get('expense_date') or datetime.now().strftime('%Y-%m-%d')
        
        if amount and category:
            cursor.execute('''INSERT INTO expenses (
                                amount, category, notes, created_by, expense_date, entity_id
                              ) VALUES (?, ?, ?, ?, ?, ?)''', 
                           (amount, category, notes, session['username'], date_val, real_entity))
            conn.commit()
            
        conn.close()
        return redirect(url_for('expenses'))
    
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    q_cond = " AND entity_id=?" if entity != 'all' else ""
    p_params = [entity] if entity != 'all' else []
    
    if date_from and date_to:
        cursor.execute(f"SELECT * FROM expenses WHERE expense_date BETWEEN ? AND ? {q_cond} ORDER BY expense_date DESC, id DESC", [date_from, date_to] + p_params)
        expenses_list = cursor.fetchall()
        
        cursor.execute(f"SELECT SUM(amount) FROM expenses WHERE expense_date BETWEEN ? AND ? {q_cond}", [date_from, date_to] + p_params)
        sum_result = cursor.fetchone()
    else:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute(f"SELECT * FROM expenses WHERE expense_date = ? {q_cond} ORDER BY id DESC", [today] + p_params)
        expenses_list = cursor.fetchall()
        
        cursor.execute(f"SELECT SUM(amount) FROM expenses WHERE expense_date = ? {q_cond}", [today] + p_params)
        sum_result = cursor.fetchone()

    total_expenses = sum_result[0] if sum_result and sum_result[0] is not None else 0.0
    conn.close()
    
    return render_template('expenses.html', expenses=expenses_list, total_expenses=total_expenses, date_from=date_from, date_to=date_to)

@app.route('/delete_expense/<int:expense_id>')
def delete_expense(expense_id):
    if not has_perm('exp', 'd'): 
        return redirect(url_for('expenses'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('expenses'))
@app.route('/reports')
def reports():
    if not has_perm('rep', 'v'):
        flash('غير مصرح لك بعرض التقارير!', 'error')
        return redirect(url_for('dashboard'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    inv_no_filter = request.args.get('invoice_no', '').strip()
    cust_name_filter = request.args.get('customer_name', '').strip()
    created_by_filter = request.args.get('created_by', '').strip()
    
    inv_cond = " WHERE 1=1"
    inv_params = []
    exp_cond = " WHERE 1=1"
    exp_params = []
    
    if entity != 'all':
        inv_cond += " AND invoices.entity_id=?"
        inv_params.append(entity)
        exp_cond += " AND entity_id=?"
        exp_params.append(entity)
        
    if date_from and date_to:
        inv_cond += " AND date(invoices.created_at) BETWEEN ? AND ?"
        inv_params.extend([date_from, date_to])
        exp_cond += " AND expense_date BETWEEN ? AND ?"
        exp_params.extend([date_from, date_to])
        
    if inv_no_filter:
        inv_cond += " AND invoices.invoice_no LIKE ?"
        inv_params.append(f"%{inv_no_filter}%")
    if cust_name_filter:
        inv_cond += " AND invoices.customer_name LIKE ?"
        inv_params.append(f"%{cust_name_filter}%")
    if created_by_filter:
        inv_cond += " AND invoices.created_by = ?"
        inv_params.append(created_by_filter)
        
    cursor.execute(f"SELECT SUM(total_amount), SUM(total_profit) FROM invoices{inv_cond}", inv_params)
    sales_data = cursor.fetchone()
    total_sales = sales_data[0] if sales_data[0] else 0.0
    total_gross_profit = sales_data[1] if sales_data[1] else 0.0
    total_cost = total_sales - total_gross_profit
    
    cursor.execute(f"SELECT SUM(amount) FROM expenses{exp_cond}", exp_params)
    total_expenses = cursor.fetchone()[0] or 0.0
    net_profit = total_gross_profit - total_expenses
    
    stats = {
        'total_sales': total_sales, 
        'total_cost': total_cost, 
        'total_expenses': total_expenses, 
        'net_profit': net_profit
    }
    
    if entity == 'all':
        cursor.execute("SELECT SUM(cost_price * stock_qty) FROM products WHERE stock_qty > 0")
        stock_val = cursor.fetchone()[0] or 0.0
        
        cursor.execute("SELECT COUNT(*) FROM products WHERE stock_qty < 5")
        low_stock = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(total_amount) FROM purchases WHERE status='pending'")
        supplier_debts = cursor.fetchone()[0] or 0.0
        
        cursor.execute("SELECT name, profit_share FROM partners")
        partners_db = cursor.fetchall()
        
        cursor.execute("SELECT DISTINCT customer_name FROM invoices WHERE customer_name IS NOT NULL AND customer_name != '' ORDER BY customer_name")
        unique_custs = [r[0] for r in cursor.fetchall()]
        
        cursor.execute("SELECT username FROM users UNION SELECT created_by FROM invoices WHERE created_by IS NOT NULL")
        unique_users = sorted([r[0] for r in cursor.fetchall() if r[0]])
    else:
        cursor.execute("SELECT SUM(cost_price * stock_qty) FROM products WHERE stock_qty > 0 AND entity_id=?", (entity,))
        stock_val = cursor.fetchone()[0] or 0.0
        
        cursor.execute("SELECT COUNT(*) FROM products WHERE stock_qty < 5 AND entity_id=?", (entity,))
        low_stock = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(total_amount) FROM purchases WHERE status='pending' AND entity_id=?", (entity,))
        supplier_debts = cursor.fetchone()[0] or 0.0
        
        cursor.execute("SELECT name, profit_share FROM partners WHERE entity_id=?", (entity,))
        partners_db = cursor.fetchall()
        
        cursor.execute("SELECT DISTINCT customer_name FROM invoices WHERE customer_name IS NOT NULL AND customer_name != '' AND entity_id=? ORDER BY customer_name", (entity,))
        unique_custs = [r[0] for r in cursor.fetchall()]
        
        cursor.execute("SELECT username FROM users WHERE parent_id=? UNION SELECT created_by FROM invoices WHERE created_by IS NOT NULL AND entity_id=?", (session['user_id'], entity))
        unique_users = sorted([r[0] for r in cursor.fetchall() if r[0]])

    inventory_stats = {'stock_value': stock_val, 'low_stock': low_stock, 'supplier_debts': supplier_debts}
    
    partners_data = []
    for p in partners_db:
        p_name = p[0]
        p_share = p[1] if p[1] else 100.0
        
        q = f"SELECT SUM(ii.profit) FROM invoice_items ii JOIN invoices ON ii.invoice_no = invoices.invoice_no {inv_cond} AND ii.partner_name = ?"
        p_params = inv_params + [p_name]
        if entity != 'all':
            q += " AND ii.entity_id=?"
            p_params.append(entity)
            
        cursor.execute(q, p_params)
        p_profit_val = cursor.fetchone()[0] or 0.0
        p_net = p_profit_val * (p_share / 100.0)
        partners_data.append({'name': p_name, 'share': p_share, 'net': p_net})
        
    cursor.execute(f"SELECT invoices.invoice_no, invoices.created_at, invoices.customer_name, invoices.total_amount, invoices.total_profit, invoices.created_by FROM invoices{inv_cond} ORDER BY invoices.id DESC LIMIT 150", inv_params)
    invoices = cursor.fetchall()
    
    conn.close()
    return render_template('reports.html', stats=stats, inventory=inventory_stats, partners=partners_data, invoices=invoices, date_from=date_from, date_to=date_to, customers=unique_custs, users=unique_users)

@app.route('/return_invoice/<invoice_no>', methods=['POST'])
def return_invoice(invoice_no):
    if not has_perm('rep', 'd'): 
        return jsonify({"error": "Unauthorized"}), 403
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    
    if entity == 'all':
        cursor.execute("SELECT product_name, qty FROM invoice_items WHERE invoice_no=?", (invoice_no,))
        items = cursor.fetchall()
        for item in items: 
            cursor.execute("UPDATE products SET stock_qty = stock_qty + ? WHERE name=?", (item[1], item[0]))
        cursor.execute("DELETE FROM invoices WHERE invoice_no=?", (invoice_no,))
        cursor.execute("DELETE FROM invoice_items WHERE invoice_no=?", (invoice_no,))
    else:
        cursor.execute("SELECT product_name, qty FROM invoice_items WHERE invoice_no=? AND entity_id=?", (invoice_no, entity))
        items = cursor.fetchall()
        for item in items: 
            cursor.execute("UPDATE products SET stock_qty = stock_qty + ? WHERE name=? AND entity_id=?", (item[1], item[0], entity))
        cursor.execute("DELETE FROM invoices WHERE invoice_no=? AND entity_id=?", (invoice_no, entity))
        cursor.execute("DELETE FROM invoice_items WHERE invoice_no=? AND entity_id=?", (invoice_no, entity))
        
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/get_invoice_details/<invoice_no>')
def get_invoice_details(invoice_no):
    if not has_perm('rep', 'v'): 
        return jsonify({"error": "Unauthorized"}), 403
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    
    if entity == 'all':
        cursor.execute("SELECT customer_name, total_amount, created_at, created_by FROM invoices WHERE invoice_no=?", (invoice_no,))
        inv_data = cursor.fetchone()
        cursor.execute("SELECT product_name, qty, sell_price, (qty*sell_price) as total_line FROM invoice_items WHERE invoice_no=?", (invoice_no,))
        items = cursor.fetchall()
    else:
        cursor.execute("SELECT customer_name, total_amount, created_at, created_by FROM invoices WHERE invoice_no=? AND entity_id=?", (invoice_no, entity))
        inv_data = cursor.fetchone()
        cursor.execute("SELECT product_name, qty, sell_price, (qty*sell_price) as total_line FROM invoice_items WHERE invoice_no=? AND entity_id=?", (invoice_no, entity))
        items = cursor.fetchall()
        
    conn.close()
    
    if inv_data: 
        return jsonify({
            "invoice_no": invoice_no, 
            "customer_name": inv_data[0], 
            "total_amount": inv_data[1], 
            "date": inv_data[2], 
            "created_by": inv_data[3] or 'غير محدد', 
            "items": [{"name": i[0], "qty": i[1], "price": i[2], "total": i[3]} for i in items]
        })
        
    return jsonify({"error": "Not Found"})

@app.route('/api/stock_details')
def api_stock_details():
    if not has_perm('rep', 'v'): 
        return jsonify({"error": "Unauthorized"}), 403
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    
    if entity == 'all': 
        cursor.execute("SELECT name, stock_qty, cost_price, partner_name FROM products WHERE stock_qty > 0")
    else: 
        cursor.execute("SELECT name, stock_qty, cost_price, partner_name FROM products WHERE stock_qty > 0 AND entity_id=?", (entity,))
        
    products_db = cursor.fetchall()
    products = []
    partners_capital = {}
    
    for p in products_db:
        name = p[0]
        qty = p[1]
        cost = p[2]
        partner = p[3] if p[3] else 'بدون شريك'
        
        products.append({"name": name, "qty": qty, "cost": cost, "partner": partner})
        
        total_val = qty * cost
        if partner in partners_capital: 
            partners_capital[partner] += total_val
        else: 
            partners_capital[partner] = total_val
            
    conn.close()
    return jsonify({"products": products, "partners_capital": partners_capital})

@app.route('/api/low_stock')
def api_low_stock():
    if not has_perm('rep', 'v'): 
        return jsonify({"error": "Unauthorized"}), 403
        
    threshold = request.args.get('threshold', 5, type=int)
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    
    if entity == 'all': 
        cursor.execute("SELECT name, stock_qty, cost_price, partner_name FROM products WHERE stock_qty < ?", (threshold,))
    else: 
        cursor.execute("SELECT name, stock_qty, cost_price, partner_name FROM products WHERE stock_qty < ? AND entity_id=?", (threshold, entity))
        
    items_db = cursor.fetchall()
    conn.close()
    
    low_stock = [{"name": item[0], "qty": item[1], "cost": item[2], "partner": item[3] if item[3] else 'بدون شريك'} for item in items_db]
    return jsonify(low_stock)

@app.route('/print_custom_low_stock', methods=['POST'])
def print_custom_low_stock():
    if not has_perm('rep', 'v'): 
        return redirect(url_for('dashboard'))
        
    data = request.form.get('data')
    if not data: 
        return "بيانات غير صالحة", 400
        
    parsed_data = json.loads(data)
    items = parsed_data.get('items', [])
    columns = parsed_data.get('columns', {})
    
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    cursor.execute("SELECT store_name, store_phone, store_branch, invoice_footer FROM store_settings WHERE entity_id=? LIMIT 1", (real_entity,))
    st_row = cursor.fetchone()
    store_info = {
        'name': st_row[0] if st_row else 'نظام المتجر الذكي', 
        'phone': st_row[1] if st_row else '01012345678'
    }
    conn.close()
    
    return render_template('print_low_stock.html', items=items, columns=columns, date=datetime.now().strftime('%Y-%m-%d'), store=store_info)

@app.route('/print_old_invoice/<invoice_no>')
def print_old_invoice(invoice_no):
    if not has_perm('rep', 'v'): 
        return redirect(url_for('dashboard'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    cursor.execute("SELECT store_name, store_phone, store_branch, invoice_footer, logo FROM store_settings WHERE entity_id=? LIMIT 1", (real_entity,))
    st_row = cursor.fetchone()
    store_info = {
        'name': st_row[0] if st_row else 'نظام المتجر', 
        'phone': st_row[1] if st_row else '', 
        'branch': st_row[2] if st_row else '', 
        'footer': st_row[3] if st_row else '',
        'logo': st_row[4] if st_row and len(st_row) > 4 else None
    }
    
    if entity == 'all':
        cursor.execute("SELECT customer_name, total_amount, created_at, created_by FROM invoices WHERE invoice_no=?", (invoice_no,))
        inv = cursor.fetchone()
        cursor.execute("SELECT product_name, qty, sell_price, partner_name FROM invoice_items WHERE invoice_no=?", (invoice_no,))
        items_db = cursor.fetchall()
    else:
        cursor.execute("SELECT customer_name, total_amount, created_at, created_by FROM invoices WHERE invoice_no=? AND entity_id=?", (invoice_no, entity))
        inv = cursor.fetchone()
        cursor.execute("SELECT product_name, qty, sell_price, partner_name FROM invoice_items WHERE invoice_no=? AND entity_id=?", (invoice_no, entity))
        items_db = cursor.fetchall()
        
    if not inv:
        conn.close()
        return "الفاتورة غير موجودة!", 404
        
    customer_name = inv[0] if inv[0] else 'عميل نقدي'
    net_total = f"{inv[1]:.2f}"
    date_str = inv[2][:10] if inv[2] else ''
    cashier_name = inv[3] if inv[3] else 'غير محدد'
    items = [{'name': item[0], 'qty': item[1], 'price': item[2], 'partner': item[3]} for item in items_db]
    
    conn.close()
    return render_template('print_invoice.html', customer_name=customer_name, items=items, subtotal=net_total, discount="0.00", net_total=net_total, date=date_str, invoice_no=invoice_no, store=store_info, cashier=cashier_name)
@app.route('/settings')
def settings():
    if 'username' not in session: 
        return redirect(url_for('login'))
    
    conn = get_db_conn()
    cursor = conn.cursor()
    
    if session.get('role') not in ['owner', 'admin']:
        conn.close()
        flash('الإعدادات متاحة للمديرين فقط.', 'error')
        return redirect(url_for('dashboard'))

    cols = "id, username, role, status, expiry_date, max_users, view_cost, view_scope, parent_id, p_sales_v, p_sales_a, p_sales_e, p_sales_d, p_prod_v, p_prod_a, p_prod_e, p_prod_d, p_purch_v, p_purch_a, p_purch_e, p_purch_d, p_exp_v, p_exp_a, p_exp_e, p_exp_d, p_rep_v, p_rep_a, p_rep_e, p_rep_d, p_part_v, p_part_a, p_part_e, p_part_d"
    
    users_tree = []
    if session.get('role') == 'owner':
        cursor.execute(f"SELECT {cols} FROM users WHERE role='admin' OR (role!='owner' AND parent_id IS NULL)")
        admins = cursor.fetchall()
        for adm in admins:
            cursor.execute(f"SELECT {cols} FROM users WHERE parent_id=?", (adm[0],))
            children = cursor.fetchall()
            users_tree.append({'admin': adm, 'children': children})
    else:
        cursor.execute(f"SELECT {cols} FROM users WHERE parent_id=?", (session.get('user_id'),))
        children = cursor.fetchall()
        users_tree.append({'admin': None, 'children': children})
    
    cursor.execute("SELECT max_users FROM users WHERE id=?", (session['user_id'],))
    my_max_res = cursor.fetchone()
    my_max_users = my_max_res[0] if my_max_res else 0
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE parent_id=?", (session['user_id'],))
    current_sub_users = cursor.fetchone()[0]
    
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    cursor.execute("SELECT store_name, store_phone, store_branch, invoice_footer, logo FROM store_settings WHERE entity_id=? LIMIT 1", (real_entity,))
    st_row = cursor.fetchone()
    if not st_row:
        cursor.execute("INSERT INTO store_settings (entity_id) VALUES (?)", (real_entity,))
        conn.commit()
        st_row = ('المتجر', '', '', '')
        
    conn.close()
    
    settings_data = {
        'store_name': st_row[0], 
        'store_phone': st_row[1], 
        'store_branch': st_row[2], 
        'footer': st_row[3],
        'logo': st_row[4] if len(st_row) > 4 else None
    }
    return render_template('settings.html', users_tree=users_tree, settings=settings_data, my_max_users=my_max_users, current_sub_users=current_sub_users)

@app.route('/add_user', methods=['POST'])
def add_user():
    if 'username' not in session or session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('dashboard'))
        
    is_owner = (session.get('role') == 'owner')
    parent_id = session.get('user_id') if not is_owner else None
    
    conn = get_db_conn()
    cursor = conn.cursor()
    
    if not is_owner:
        cursor.execute("SELECT max_users FROM users WHERE id=?", (session['user_id'],))
        max_u = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM users WHERE parent_id=?", (session['user_id'],))
        if cursor.fetchone()[0] >= max_u:
            conn.close()
            flash('لقد وصلت للحد الأقصى لباقتك!', 'error')
            return redirect(url_for('settings'))
            
    username = request.form['username']
    password = request.form['password']
    role = request.form['role']
    
    def get_p(field): 
        return 1 if request.form.get(field) == '1' and (is_owner or session.get(field)==1) else 0

    sv, sa, se, sd = get_p('p_sales_v'), get_p('p_sales_a'), get_p('p_sales_e'), get_p('p_sales_d')
    pv, pa, pe, pd = get_p('p_prod_v'), get_p('p_prod_a'), get_p('p_prod_e'), get_p('p_prod_d')
    puv, pua, pue, pud = get_p('p_purch_v'), get_p('p_purch_a'), get_p('p_purch_e'), get_p('p_purch_d')
    ev, ea, ee, ed = get_p('p_exp_v'), get_p('p_exp_a'), get_p('p_exp_e'), get_p('p_exp_d')
    rv, ra, re, rd = get_p('p_rep_v'), get_p('p_rep_a'), get_p('p_rep_e'), get_p('p_rep_d')
    pav, paa, pae, pad = get_p('p_part_v'), get_p('p_part_a'), get_p('p_part_e'), get_p('p_part_d')
    
    view_cost = request.form.get('view_cost', 'none')
    if not is_owner and view_cost == 'all' and session.get('view_cost') != 'all': 
        view_cost = session.get('view_cost')
        
    view_scope = request.form.get('view_scope', 'own')
    if not is_owner and view_scope == 'all' and session.get('view_scope') != 'all': 
        view_scope = session.get('view_scope')
        
    status = request.form.get('status', 'active') if is_owner else 'active'
    expiry = request.form.get('expiry_date') if is_owner else None
    max_u = request.form.get('max_users', 0) if is_owner else 0
    
    cursor.execute("SELECT id FROM users WHERE username=?", (username,))
    if cursor.fetchone():
        flash('اسم المستخدم موجود مسبقاً!', 'error')
        conn.close()
        return redirect(url_for('settings'))
        
    hashed_pw = generate_password_hash(password)
    
    cursor.execute('''INSERT INTO users (
                        username, password, role, parent_id, view_cost, view_scope, status, expiry_date, max_users, 
                        p_sales_v, p_sales_a, p_sales_e, p_sales_d, 
                        p_prod_v, p_prod_a, p_prod_e, p_prod_d, 
                        p_purch_v, p_purch_a, p_purch_e, p_purch_d, 
                        p_exp_v, p_exp_a, p_exp_e, p_exp_d, 
                        p_rep_v, p_rep_a, p_rep_e, p_rep_d, 
                        p_part_v, p_part_a, p_part_e, p_part_d
                      ) VALUES (?,?,?,?,?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?)''', 
                   (username, hashed_pw, role, parent_id, view_cost, view_scope, status, expiry, max_u, 
                    sv, sa, se, sd, pv, pa, pe, pd, puv, pua, pue, pud, ev, ea, ee, ed, rv, ra, re, rd, pav, paa, pae, pad))
                    
    conn.commit()
    conn.close()
    flash('تم إضافة الحساب بنجاح!', 'success')
    return redirect(url_for('settings'))

@app.route('/update_user_permissions/<int:user_id>', methods=['POST'])
def update_user_permissions(user_id):
    if 'username' not in session or session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('dashboard'))
        
    is_owner = (session.get('role') == 'owner')
    
    def get_p(field): 
        return 1 if request.form.get(field) == '1' and (is_owner or session.get(field)==1) else 0

    sv, sa, se, sd = get_p('p_sales_v'), get_p('p_sales_a'), get_p('p_sales_e'), get_p('p_sales_d')
    pv, pa, pe, pd = get_p('p_prod_v'), get_p('p_prod_a'), get_p('p_prod_e'), get_p('p_prod_d')
    puv, pua, pue, pud = get_p('p_purch_v'), get_p('p_purch_a'), get_p('p_purch_e'), get_p('p_purch_d')
    ev, ea, ee, ed = get_p('p_exp_v'), get_p('p_exp_a'), get_p('p_exp_e'), get_p('p_exp_d')
    rv, ra, re, rd = get_p('p_rep_v'), get_p('p_rep_a'), get_p('p_rep_e'), get_p('p_rep_d')
    pav, paa, pae, pad = get_p('p_part_v'), get_p('p_part_a'), get_p('p_part_e'), get_p('p_part_d')

    view_cost = request.form.get('view_cost', 'none')
    if not is_owner and view_cost == 'all' and session.get('view_cost') != 'all': 
        view_cost = session.get('view_cost')
        
    view_scope = request.form.get('view_scope', 'own')
    if not is_owner and view_scope == 'all' and session.get('view_scope') != 'all': 
        view_scope = session.get('view_scope')
        
    status = request.form.get('status', 'active') if is_owner else 'active'
    expiry = request.form.get('expiry_date') if is_owner else None
    max_u = request.form.get('max_users', 0) if is_owner else 0
    new_pass = request.form.get('reset_password', '').strip()
    
    conn = get_db_conn()
    cursor = conn.cursor()
    
    base_query = '''UPDATE users SET view_cost=?, view_scope=?, 
                    p_sales_v=?, p_sales_a=?, p_sales_e=?, p_sales_d=?, 
                    p_prod_v=?, p_prod_a=?, p_prod_e=?, p_prod_d=?, 
                    p_purch_v=?, p_purch_a=?, p_purch_e=?, p_purch_d=?, 
                    p_exp_v=?, p_exp_a=?, p_exp_e=?, p_exp_d=?, 
                    p_rep_v=?, p_rep_a=?, p_rep_e=?, p_rep_d=?, 
                    p_part_v=?, p_part_a=?, p_part_e=?, p_part_d=?'''
                    
    params = [view_cost, view_scope, sv, sa, se, sd, pv, pa, pe, pd, puv, pua, pue, pud, ev, ea, ee, ed, rv, ra, re, rd, pav, paa, pae, pad]

    if is_owner:
        base_query += ", status=?, expiry_date=?, max_users=?"
        params.extend([status, expiry, max_u])
        
    if new_pass:
        base_query += ", password=?"
        params.append(generate_password_hash(new_pass))
        
    base_query += " WHERE id=?"
    params.append(user_id)
    
    cursor.execute(base_query, tuple(params))
    conn.commit()
    conn.close()
    flash('تم التحديث بنجاح! قد يحتاج الموظف لتسجيل الدخول مجدداً.', 'success')
    return redirect(url_for('settings'))

@app.route('/delete_user/<int:user_id>')
def delete_user(user_id):
    if session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('dashboard'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
    cursor.execute("DELETE FROM users WHERE parent_id=?", (user_id,))
    conn.commit()
    conn.close()
    flash('تم الحذف.', 'success')
    return redirect(url_for('settings'))

@app.route('/update_invoice_settings', methods=['POST'])
def update_invoice_settings():
    if 'username' not in session or session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('dashboard'))
        
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    store_name = request.form['store_name']
    store_phone = request.form['store_phone']
    store_branch = request.form['store_branch']
    invoice_footer = request.form['invoice_footer']
    
    logo_file = request.files.get('store_logo')
    logo_filename = None
    if logo_file and logo_file.filename != '':
        filename = secure_filename(logo_file.filename)
        logo_filename = f"logo_{real_entity}_{filename}"
        logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], logo_filename))
    
    conn = get_db_conn()
    cursor = conn.cursor()
    
    if logo_filename:
        cursor.execute('''UPDATE store_settings 
                          SET store_name=?, store_phone=?, store_branch=?, invoice_footer=?, logo=? 
                          WHERE entity_id=?''', 
                       (store_name, store_phone, store_branch, invoice_footer, logo_filename, real_entity))
    else:
        cursor.execute('''UPDATE store_settings 
                          SET store_name=?, store_phone=?, store_branch=?, invoice_footer=? 
                          WHERE entity_id=?''', 
                       (store_name, store_phone, store_branch, invoice_footer, real_entity))
                       
    conn.commit()
    conn.close()
    flash('تم حفظ إعدادات المتجر!', 'success')
    return redirect(url_for('settings'))
@app.route('/remove_logo', methods=['POST'])
def remove_logo():
    if 'username' not in session or session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('dashboard'))
        
    real_entity = get_entity() if get_entity() != 'all' else 1
    conn = get_db_conn()
    cursor = conn.cursor()
    
    # نجيب اسم اللوجو الأول عشان نمسح الملف من السيرفر
    cursor.execute("SELECT logo FROM store_settings WHERE entity_id=?", (real_entity,))
    row = cursor.fetchone()
    
    if row and row[0]:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], row[0]))
        except Exception:
            pass # لو الملف مش موجود متعملش إيرور
            
    # نحذف اسم اللوجو من الداتابيز
    cursor.execute("UPDATE store_settings SET logo=NULL WHERE entity_id=?", (real_entity,))
    conn.commit()
    conn.close()
    
    flash('تم حذف الشعار بنجاح!', 'success')
    return redirect(url_for('settings'))

@app.route('/change_password', methods=['POST'])
def change_password():
    if 'username' not in session: 
        return redirect(url_for('login'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username=?", (session['username'],))
    user = cursor.fetchone()
    
    if not user:
        flash('المستخدم غير موجود!', 'error')
    else:
        is_valid = False
        if check_password_hash(user[2], request.form['old_password']):
            is_valid = True
        elif user[2] == request.form['old_password']:
            is_valid = True
            
        if is_valid:
            hashed_new = generate_password_hash(request.form['new_password'])
            cursor.execute("UPDATE users SET password=? WHERE username=?", (hashed_new, session['username']))
            conn.commit()
            flash('تم تغيير كلمة المرور بنجاح!', 'success')
        else:
            flash('كلمة المرور الحالية غير صحيحة!', 'error')
            
    conn.close()
    return redirect(url_for('settings'))

@app.route('/backup_db')
def backup_db():
    role = session.get('role')
    if 'username' not in session or role not in ['owner', 'admin']: 
        return redirect(url_for('dashboard'))
        
    if role == 'owner':
        db_path = 'store_db.sqlite'
        if os.path.exists(db_path): 
            return send_file(db_path, as_attachment=True, download_name=f"store_backup_{datetime.now().strftime('%Y-%m-%d')}.sqlite")
        return "ملف قاعدة البيانات غير موجود!", 404
        
    else:
        real_entity = session.get('user_id')
        backup_filename = f"store_backup_{session.get('username')}_{datetime.now().strftime('%Y-%m-%d')}.sqlite"
        temp_path = f"temp_{backup_filename}"
        
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
                
        src_conn = get_db_conn()
        dst_conn = sqlite3.connect(temp_path)
        src_cursor = src_conn.cursor()
        dst_cursor = dst_conn.cursor()
        
        cursor = src_conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall() if row[0] != 'sqlite_sequence']
        
        for table in tables:
            src_cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?;", (table,))
            ddl_res = src_cursor.fetchone()
            if ddl_res and ddl_res[0]: 
                dst_cursor.execute(ddl_res[0])
                
            src_cursor.execute(f"PRAGMA table_info({table});")
            cols = [col[1] for col in src_cursor.fetchall()]
            if not cols: 
                continue
            
            placeholders = ','.join(['?'] * len(cols))
            
            if 'entity_id' in cols:
                src_cursor.execute(f"SELECT * FROM {table} WHERE entity_id=?", (real_entity,))
                rows = src_cursor.fetchall()
                if rows: 
                    dst_cursor.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
            
            elif table == 'users':
                src_cursor.execute(f"SELECT * FROM users WHERE id=? OR parent_id=?", (real_entity, real_entity))
                rows = src_cursor.fetchall()
                if rows: 
                    dst_cursor.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
            
            elif table == 'store_settings':
                src_cursor.execute(f"SELECT * FROM store_settings WHERE entity_id=?", (real_entity,))
                rows = src_cursor.fetchall()
                if rows: 
                    dst_cursor.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
                    
        dst_conn.commit()
        src_conn.close()
        dst_conn.close()
        
        @after_this_request
        def remove_file(response):
            try: os.remove(temp_path)
            except Exception: pass
            return response
            
        return send_file(temp_path, as_attachment=True, download_name=backup_filename)

@app.route('/import_db', methods=['POST'])
def import_db():
    role = session.get('role')
    if 'username' not in session or role not in ['owner', 'admin']: 
        return redirect(url_for('dashboard'))
        
    file = request.files.get('backup_file')
    if not file or file.filename == '':
        flash('لم يتم اختيار ملف!', 'error')
        return redirect(url_for('settings'))
        
    if role == 'owner':
        file.save('store_db.sqlite')
        init_db()
        init_settings_table()
        flash('تم استيراد قاعدة البيانات للنظام بالكامل بنجاح!', 'success')
        
    else:
        real_entity = session.get('user_id')
        temp_path = f"temp_upload_{real_entity}_{int(datetime.now().timestamp())}.sqlite"
        file.save(temp_path)
        
        try:
            main_conn = get_db_conn()
            up_conn = sqlite3.connect(temp_path)
            main_cursor = main_conn.cursor()
            up_cursor = up_conn.cursor()
            
            up_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in up_cursor.fetchall() if row[0] != 'sqlite_sequence']
            
            for table in tables:
                main_cursor.execute(f"PRAGMA table_info({table});")
                cols = [col[1] for col in main_cursor.fetchall()]
                if not cols: 
                    continue
                
                placeholders = ','.join(['?'] * len(cols))
                
                if 'entity_id' in cols:
                    main_cursor.execute(f"DELETE FROM {table} WHERE entity_id=?", (real_entity,))
                    up_cursor.execute(f"SELECT * FROM {table} WHERE entity_id=?", (real_entity,))
                    rows = up_cursor.fetchall()
                    if rows: 
                        main_cursor.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
                
                elif table == 'users':
                    main_cursor.execute("DELETE FROM users WHERE parent_id=?", (real_entity,))
                    main_cursor.execute("DELETE FROM users WHERE id=?", (real_entity,))
                    up_cursor.execute("SELECT * FROM users WHERE id=? OR parent_id=?", (real_entity, real_entity))
                    rows = up_cursor.fetchall()
                    if rows: 
                        main_cursor.executemany(f"INSERT INTO users VALUES ({placeholders})", rows)
                    
                elif table == 'store_settings':
                    main_cursor.execute("DELETE FROM store_settings WHERE entity_id=?", (real_entity,))
                    up_cursor.execute("SELECT * FROM store_settings WHERE entity_id=?", (real_entity,))
                    rows = up_cursor.fetchall()
                    if rows: 
                        main_cursor.executemany(f"INSERT INTO store_settings VALUES ({placeholders})", rows)
                    
            main_conn.commit()
            main_conn.close()
            up_conn.close()
            flash('تم استعادة بيانات متجرك بنجاح!', 'success')
            
        except Exception as e:
            flash('حدث خطأ أثناء الاستعادة، تأكد أن الملف سليم وصالح.', 'error')
        finally:
            if os.path.exists(temp_path):
                try: os.remove(temp_path)
                except: pass
                
    return redirect(url_for('settings'))

@app.route('/purge_data', methods=['POST'])
def purge_data():
    role = session.get('role')
    if role not in ['owner', 'admin']: 
        return redirect(url_for('dashboard'))
        
    target = request.form.get('target')
    conn = get_db_conn()
    cursor = conn.cursor()
    
    is_owner = (role == 'owner')
    real_entity = session.get('user_id') if not is_owner else None
    
    try:
        if is_owner:
            if target == 'invoices':
                cursor.execute("DELETE FROM invoices")
                cursor.execute("DELETE FROM invoice_items")
            elif target == 'purchases':
                cursor.execute("DELETE FROM purchases")
                cursor.execute("DELETE FROM purchase_items")
            elif target == 'expenses':
                cursor.execute("DELETE FROM expenses")
            elif target == 'partners':
                cursor.execute("UPDATE invoice_items SET partner_name='بدون شريك'")
                cursor.execute("UPDATE purchase_items SET partner_name='بدون شريك'")
                cursor.execute("UPDATE products SET partner_name='بدون شريك'")
                cursor.execute("DELETE FROM partners")
                cursor.execute("DELETE FROM partner_withdrawals")
            elif target == 'factory_reset':
                for t in ['invoices', 'invoice_items', 'purchases', 'purchase_items', 'expenses', 'partners', 'products', 'partner_withdrawals']: 
                    cursor.execute(f"DELETE FROM {t}")
                    
        else:
            if target == 'invoices':
                cursor.execute("DELETE FROM invoice_items WHERE entity_id=?", (real_entity,))
                cursor.execute("DELETE FROM invoices WHERE entity_id=?", (real_entity,))
            elif target == 'purchases':
                cursor.execute("DELETE FROM purchase_items WHERE entity_id=?", (real_entity,))
                cursor.execute("DELETE FROM purchases WHERE entity_id=?", (real_entity,))
            elif target == 'expenses':
                cursor.execute("DELETE FROM expenses WHERE entity_id=?", (real_entity,))
            elif target == 'partners':
                cursor.execute("UPDATE invoice_items SET partner_name='بدون شريك' WHERE entity_id=?", (real_entity,))
                cursor.execute("UPDATE purchase_items SET partner_name='بدون شريك' WHERE entity_id=?", (real_entity,))
                cursor.execute("UPDATE products SET partner_name='بدون شريك' WHERE entity_id=?", (real_entity,))
                cursor.execute("DELETE FROM partners WHERE entity_id=?", (real_entity,))
                cursor.execute("DELETE FROM partner_withdrawals WHERE entity_id=?", (real_entity,))
            elif target == 'factory_reset':
                for t in ['invoices', 'invoice_items', 'purchases', 'purchase_items', 'expenses', 'partners', 'products', 'partner_withdrawals']: 
                    cursor.execute(f"DELETE FROM {t} WHERE entity_id=?", (real_entity,))
                
        conn.commit()
        flash('تمت العملية المطلوبة بنجاح!', 'success')
    except Exception as e:
        flash(f'حدث خطأ: {e}', 'error')
        
    conn.close()
    return redirect(url_for('settings'))

@app.route('/super_admin')
def super_admin():
    if session.get('role') != 'owner':
        return redirect(url_for('dashboard'))
    
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row  
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT u.*, 
        (SELECT COUNT(*) FROM users WHERE parent_id = u.id) as emp_count 
        FROM users u 
        WHERE u.role != 'owner' AND u.parent_id IS NULL 
        ORDER BY u.id DESC
    """)
    raw_users = cursor.fetchall()
    all_users = [dict(row) for row in raw_users]
    
    conn.close()
    return render_template('super_admin.html', users=all_users)

@app.route('/super_admin_edit/<int:user_id>', methods=['POST'])
def super_admin_edit(user_id):
    if session.get('role') != 'owner':
        return redirect(url_for('dashboard'))
        
    status = request.form.get('status', 'active')
    expiry = request.form.get('expiry_date') or None
    max_u = request.form.get('max_users', 0)
    
    def get_p(field): return 1 if request.form.get(field) == '1' else 0
    
    sv, sa, se, sd = get_p('p_sales_v'), get_p('p_sales_a'), get_p('p_sales_e'), get_p('p_sales_d')
    pv, pa, pe, pd = get_p('p_prod_v'), get_p('p_prod_a'), get_p('p_prod_e'), get_p('p_prod_d')
    puv, pua, pue, pud = get_p('p_purch_v'), get_p('p_purch_a'), get_p('p_purch_e'), get_p('p_purch_d')
    ev, ea, ee, ed = get_p('p_exp_v'), get_p('p_exp_a'), get_p('p_exp_e'), get_p('p_exp_d')
    rv, ra, re, rd = get_p('p_rep_v'), get_p('p_rep_a'), get_p('p_rep_e'), get_p('p_rep_d')
    pav, paa, pae, pad = get_p('p_part_v'), get_p('p_part_a'), get_p('p_part_e'), get_p('p_part_d')

    conn = get_db_conn()
    cursor = conn.cursor()
    
    cursor.execute('''UPDATE users SET 
        status=?, expiry_date=?, max_users=?,
        p_sales_v=?, p_sales_a=?, p_sales_e=?, p_sales_d=?,
        p_prod_v=?, p_prod_a=?, p_prod_e=?, p_prod_d=?,
        p_purch_v=?, p_purch_a=?, p_purch_e=?, p_purch_d=?,
        p_exp_v=?, p_exp_a=?, p_exp_e=?, p_exp_d=?,
        p_rep_v=?, p_rep_a=?, p_rep_e=?, p_rep_d=?,
        p_part_v=?, p_part_a=?, p_part_e=?, p_part_d=?
        WHERE id=?''', (
        status, expiry, max_u,
        sv, sa, se, sd, pv, pa, pe, pd, puv, pua, pue, pud, 
        ev, ea, ee, ed, rv, ra, re, rd, pav, paa, pae, pad,
        user_id
    ))
    
    if status == 'suspended':
        cursor.execute("UPDATE users SET status='suspended' WHERE parent_id=?", (user_id,))
         
    conn.commit()
    conn.close()
    flash('تم حفظ تعديلات الباقة والصلاحيات بنجاح!', 'success')
    return redirect(url_for('super_admin'))

@app.route('/api/get_employees/<int:parent_id>')
def get_employees(parent_id):
    if session.get('role') != 'owner': 
        return jsonify({"error": "Unauthorized"}), 403
        
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, username, role, status FROM users WHERE parent_id=?", (parent_id,))
    emps = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return jsonify(emps)

@app.route('/super_admin_emp_action', methods=['POST'])
def super_admin_emp_action():
    if session.get('role') != 'owner': 
        return redirect(url_for('dashboard'))
        
    emp_id = request.form.get('emp_id')
    action = request.form.get('action') 
    
    conn = get_db_conn()
    cursor = conn.cursor()
    
    if action == 'toggle':
        cursor.execute("SELECT status FROM users WHERE id=?", (emp_id,))
        res = cursor.fetchone()
        if res:
            new_status = 'suspended' if res[0] == 'active' else 'active'
            cursor.execute("UPDATE users SET status=? WHERE id=?", (new_status, emp_id))
            flash('تم تغيير حالة الموظف بنجاح!', 'success')
            
    elif action == 'reset_pass':
        new_pass = request.form.get('new_pass')
        if new_pass:
            hashed_pw = generate_password_hash(new_pass)
            cursor.execute("UPDATE users SET password=? WHERE id=?", (hashed_pw, emp_id))
            flash('تم تغيير كلمة مرور الموظف بنجاح!', 'success')
            
    elif action == 'delete':
        cursor.execute("DELETE FROM users WHERE id=?", (emp_id,))
        flash('تم حذف حساب الموظف نهائياً!', 'success')
        
    conn.commit()
    conn.close()
    return redirect(url_for('super_admin'))

@app.route('/contact')
def contact():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('contact.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)