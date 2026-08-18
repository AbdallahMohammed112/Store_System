# هذا الملف مسئول عن إدارة المنتجات: إضافتها، تعديلها، وعرضها في المخزن.

import sqlite3
from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from database import get_db_conn
from auth import has_perm, get_entity

products_bp = Blueprint('products', __name__)

@products_bp.route('/products', methods=['GET', 'POST'])
def products_page():
    if not has_perm('prod', 'v'):
        flash('غير مصرح لك بعرض المنتجات!', 'error')
        return redirect(url_for('auth.dashboard'))
        
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
            return redirect(url_for('products.products_page'))
            
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
        return redirect(url_for('products.products_page'))
    
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

@products_bp.route('/delete_product/<int:id>')
def delete_product(id):
    if not has_perm('prod', 'd'): 
        return redirect(url_for('products.products_page'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('products.products_page'))

@products_bp.route('/edit_product', methods=['POST'])
def edit_product():
    if not has_perm('prod', 'e'): 
        return redirect(url_for('products.products_page'))
        
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
    return redirect(url_for('products.products_page'))