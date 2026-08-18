# هذا الملف مسئول عن التقارير الشاملة، الأرباح، النواقص، واسترجاع الفواتير.

import sqlite3
import json
from datetime import datetime
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from database import get_db_conn
from auth import has_perm, get_entity

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/reports')
def reports_page():
    if not has_perm('rep', 'v'):
        flash('غير مصرح لك بعرض التقارير!', 'error')
        return redirect(url_for('auth.dashboard'))
        
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

@reports_bp.route('/return_invoice/<invoice_no>', methods=['POST'])
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

@reports_bp.route('/get_invoice_details/<invoice_no>')
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

@reports_bp.route('/api/stock_details')
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

@reports_bp.route('/api/low_stock')
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

@reports_bp.route('/print_custom_low_stock', methods=['POST'])
def print_custom_low_stock():
    if not has_perm('rep', 'v'): 
        return redirect(url_for('auth.dashboard'))
        
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

@reports_bp.route('/print_old_invoice/<invoice_no>')
def print_old_invoice(invoice_no):
    if not has_perm('rep', 'v'): 
        return redirect(url_for('auth.dashboard'))
        
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