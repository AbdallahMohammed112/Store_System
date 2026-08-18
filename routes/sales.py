# هذا الملف مسئول عن شاشة الكاشير (نقطة البيع) وإصدار الفواتير وطباعتها.

import sqlite3
from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from datetime import datetime
from database import get_db_conn
from auth import has_perm, get_entity

sales_bp = Blueprint('sales', __name__)

@sales_bp.route('/sales')
def sales_page():
    if not has_perm('sales', 'v'):
        flash('غير مصرح لك بدخول نقطة البيع!', 'error')
        return redirect(url_for('auth.dashboard'))
        
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row  
    cursor = conn.cursor()
    entity = get_entity()
    current_user = session.get('username')
    
    can_view_all_products = (session.get('view_scope') == 'all' or session.get('role') in ['owner', 'admin'])
    can_view_cost = (session.get('view_cost') == 'all' or session.get('role') in ['owner', 'admin'])
    
    # تم إزالة شرط (stock_qty > 0) لكي تظهر كل المنتجات دائمًا في القائمة المنسدلة
    if entity == 'all':
        cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name FROM products")
        raw_products = cursor.fetchall()
        cursor.execute("SELECT * FROM partners")
        partners = cursor.fetchall()
        cursor.execute("SELECT store_name, store_phone, store_branch, invoice_footer, logo FROM store_settings LIMIT 1")
        st_row = cursor.fetchone()
    else:
        if can_view_all_products:
            cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name FROM products WHERE (entity_id=? OR 1=1)", (entity,))
        else:
            cursor.execute("SELECT id, name, cost_price, sell_price, stock_qty, partner_name FROM products WHERE entity_id=? AND created_by=?", (entity, current_user))
            
        raw_products = cursor.fetchall()
        cursor.execute("SELECT * FROM partners WHERE entity_id=?", (entity,))
        partners = cursor.fetchall()
        cursor.execute("SELECT store_name, store_phone, store_branch, invoice_footer, logo FROM store_settings WHERE entity_id=? LIMIT 1", (entity,))
        st_row = cursor.fetchone()
        
    available_products = []
    for p in raw_products:
        # تحويل البيانات لـ List لكي يقرأها ملف HTML بالأرقام (p[0], p[1]) بنجاح
        p_list = list(p)
        if not can_view_cost:
            p_list[2] = 0.0  # إخفاء سعر التكلفة إذا لم يكن يملك صلاحية
        available_products.append(p_list)
        
    store_info = {
        'name': st_row['store_name'] if st_row else 'المتجر',
        'phone': st_row['store_phone'] if st_row else '',
        'branch': st_row['store_branch'] if st_row else '',
        'footer': st_row['invoice_footer'] if st_row else '',
        'logo': st_row['logo'] if st_row and 'logo' in st_row.keys() else None
    }
    
    conn.close()

    # التوجيه للواجهة المناسبة بناءً على اختيار الموظف من الإعدادات
    if session.get('pos_view') == 'mobile':
        return render_template('sales_mobile.html', products=available_products, partners=partners, store=store_info)
        
    return render_template('sales.html', products=available_products, partners=partners, store=store_info)

@sales_bp.route('/print_receipt', methods=['POST'])
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