# هذا الملف مسئول عن المشتريات وتوريد البضاعة وتسعيرها لإضافتها للمخزن.

import sqlite3
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from database import get_db_conn
from auth import has_perm, get_entity

purchases_bp = Blueprint('purchases', __name__)

@purchases_bp.route('/purchases')
def purchases_page():
    if not has_perm('purch', 'v'):
        flash('غير مصرح لك بالدخول للمشتريات!', 'error')
        return redirect(url_for('auth.dashboard'))
        
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

@purchases_bp.route('/save_purchase', methods=['POST'])
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

@purchases_bp.route('/review_purchase/<int:purchase_id>')
def review_purchase(purchase_id):
    if not has_perm('purch', 'v'): 
        return redirect(url_for('auth.dashboard'))
        
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

@purchases_bp.route('/commit_purchase/<int:purchase_id>', methods=['POST'])
def commit_purchase(purchase_id):
    if not has_perm('purch', 'e'): 
        return redirect(url_for('auth.dashboard'))
        
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

@purchases_bp.route('/view_purchase/<int:purchase_id>')
def view_purchase(purchase_id):
    if not has_perm('purch', 'v'): 
        return redirect(url_for('auth.dashboard'))
        
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