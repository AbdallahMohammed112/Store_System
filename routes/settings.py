import sqlite3
import os
from datetime import datetime
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, send_file, after_this_request, current_app, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from database import get_db_conn, init_db, init_settings_table
from auth import get_entity

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/settings')
def settings_page():
    if 'username' not in session: 
        return redirect(url_for('auth.login'))
    
    conn = get_db_conn()
    cursor = conn.cursor()
    
    if session.get('role') not in ['owner', 'admin']:
        conn.close()
        flash('الإعدادات متاحة للمديرين فقط.', 'error')
        return redirect(url_for('auth.dashboard'))

    cols = "id, username, role, status, expiry_date, max_users, view_cost, view_scope, parent_id, p_sales_v, p_sales_a, p_sales_e, p_sales_d, p_prod_v, p_prod_a, p_prod_e, p_prod_d, p_purch_v, p_purch_a, p_purch_e, p_purch_d, p_exp_v, p_exp_a, p_exp_e, p_exp_d, p_rep_v, p_rep_a, p_rep_e, p_rep_d, p_part_v, p_part_a, p_part_e, p_part_d, allow_mobile_pos"
    
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

@settings_bp.route('/add_user', methods=['POST'])
def add_user():
    if 'username' not in session or session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('auth.dashboard'))
        
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
            return redirect(url_for('settings.settings_page'))
            
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
        return redirect(url_for('settings.settings_page'))
        
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
    return redirect(url_for('settings.settings_page'))

@settings_bp.route('/update_user_permissions/<int:user_id>', methods=['POST'])
def update_user_permissions(user_id):
    if 'username' not in session or session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('auth.dashboard'))
        
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
    flash('تم التحديث بنجاح!', 'success')
    return redirect(url_for('settings.settings_page'))

@settings_bp.route('/delete_user/<int:user_id>')
def delete_user(user_id):
    if session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('auth.dashboard'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
    cursor.execute("DELETE FROM users WHERE parent_id=?", (user_id,))
    conn.commit()
    conn.close()
    flash('تم الحذف.', 'success')
    return redirect(url_for('settings.settings_page'))

@settings_bp.route('/update_invoice_settings', methods=['POST'])
def update_invoice_settings():
    if 'username' not in session or session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('auth.dashboard'))
        
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
        logo_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], logo_filename))
    
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
    return redirect(url_for('settings.settings_page'))

@settings_bp.route('/remove_logo', methods=['POST'])
def remove_logo():
    if 'username' not in session or session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('auth.dashboard'))
        
    real_entity = get_entity() if get_entity() != 'all' else 1
    conn = get_db_conn()
    cursor = conn.cursor()
    
    cursor.execute("SELECT logo FROM store_settings WHERE entity_id=?", (real_entity,))
    row = cursor.fetchone()
    
    if row and row[0]:
        try:
            os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], row[0]))
        except Exception:
            pass
            
    cursor.execute("UPDATE store_settings SET logo=NULL WHERE entity_id=?", (real_entity,))
    conn.commit()
    conn.close()
    
    flash('تم حذف الشعار بنجاح!', 'success')
    return redirect(url_for('settings.settings_page'))

@settings_bp.route('/change_password', methods=['POST'])
def change_password():
    if 'username' not in session: 
        return redirect(url_for('auth.login'))
        
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
    return redirect(url_for('settings.settings_page'))

@settings_bp.route('/backup_db')
def backup_db():
    role = session.get('role')
    if 'username' not in session or role not in ['owner', 'admin']: 
        return redirect(url_for('auth.dashboard'))
        
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

@settings_bp.route('/import_db', methods=['POST'])
def import_db():
    role = session.get('role')
    if 'username' not in session or role not in ['owner', 'admin']: 
        return redirect(url_for('auth.dashboard'))
        
    file = request.files.get('backup_file')
    if not file or file.filename == '':
        flash('لم يتم اختيار ملف!', 'error')
        return redirect(url_for('settings.settings_page'))
        
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
                
    return redirect(url_for('settings.settings_page'))

@settings_bp.route('/purge_data', methods=['POST'])
def purge_data():
    role = session.get('role')
    if role not in ['owner', 'admin']: 
        return redirect(url_for('auth.dashboard'))
        
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
    return redirect(url_for('settings.settings_page'))

@settings_bp.route('/super_admin')
def super_admin():
    if session.get('role') != 'owner':
        return redirect(url_for('auth.dashboard'))
    
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

@settings_bp.route('/super_admin_edit/<int:user_id>', methods=['POST'])
def super_admin_edit(user_id):
    if session.get('role') != 'owner':
        return redirect(url_for('auth.dashboard'))
        
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

    allow_mobile = 1 if request.form.get('allow_mobile_pos') == '1' else 0

    conn = get_db_conn()
    cursor = conn.cursor()
    
    cursor.execute('''UPDATE users SET 
        status=?, expiry_date=?, max_users=?,
        p_sales_v=?, p_sales_a=?, p_sales_e=?, p_sales_d=?,
        p_prod_v=?, p_prod_a=?, p_prod_e=?, p_prod_d=?,
        p_purch_v=?, p_purch_a=?, p_purch_e=?, p_purch_d=?,
        p_exp_v=?, p_exp_a=?, p_exp_e=?, p_exp_d=?,
        p_rep_v=?, p_rep_a=?, p_rep_e=?, p_rep_d=?,
        p_part_v=?, p_part_a=?, p_part_e=?, p_part_d=?,
        allow_mobile_pos=?
        WHERE id=?''', (
        status, expiry, max_u,
        sv, sa, se, sd, pv, pa, pe, pd, puv, pua, pue, pud, 
        ev, ea, ee, ed, rv, ra, re, rd, pav, paa, pae, pad,
        allow_mobile, user_id
    ))
    
    if status == 'suspended':
        cursor.execute("UPDATE users SET status='suspended' WHERE parent_id=?", (user_id,))
         
    conn.commit()
    conn.close()
    flash('تم حفظ تعديلات الباقة والصلاحيات بنجاح!', 'success')
    return redirect(url_for('settings.super_admin'))

@settings_bp.route('/api/get_employees/<int:parent_id>')
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

@settings_bp.route('/super_admin_emp_action', methods=['POST'])
def super_admin_emp_action():
    if session.get('role') != 'owner': 
        return redirect(url_for('auth.dashboard'))
        
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
    return redirect(url_for('settings.super_admin'))

@settings_bp.route('/toggle_pos_view', methods=['POST'])
def toggle_pos_view():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    view = request.form.get('pos_view', 'desktop')
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET pos_view=? WHERE id=?", (view, session['user_id']))
        conn.commit()
    except Exception as e:
        print(f"Error updating POS view: {e}")
    conn.close()
    
    session['pos_view'] = view
    flash('تم تغيير شكل واجهة الكاشير بنجاح!', 'success')
    return redirect(url_for('settings.settings_page'))