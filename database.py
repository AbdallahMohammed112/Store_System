import sqlite3
from datetime import date
from werkzeug.security import generate_password_hash

def get_db_conn():
    conn = sqlite3.connect('store_db.sqlite', timeout=20)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    conn = get_db_conn()
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        username TEXT NOT NULL, 
                        password TEXT NOT NULL, 
                        role TEXT DEFAULT 'admin'
                    )''')
    
    modules = ['sales', 'prod', 'purch', 'exp', 'rep', 'part']
    actions = ['v', 'a', 'e', 'd']
    for mod in modules:
        for act in actions:
            try: 
                cursor.execute(f"ALTER TABLE users ADD COLUMN p_{mod}_{act} INTEGER DEFAULT 0")
            except sqlite3.OperationalError: 
                pass

    columns_to_add = [
        ("parent_id", "INTEGER"),
        ("view_cost", "TEXT DEFAULT 'all'"),
        ("view_scope", "TEXT DEFAULT 'own'"),
        ("status", "TEXT DEFAULT 'active'"),
        ("expiry_date", "DATE"),
        ("max_users", "INTEGER DEFAULT 0"),
        ("pos_view", "TEXT DEFAULT 'desktop'"),
        ("allow_mobile_pos", "INTEGER DEFAULT 0")
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
                            p_part_v, p_part_a, p_part_e, p_part_d, allow_mobile_pos
                          ) VALUES (
                            'admin', ?, 'owner', 'all', 'all', 'active', 999, 
                            1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,1, 1
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