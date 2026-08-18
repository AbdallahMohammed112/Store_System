# هذا الملف مسئول عن إدارة الشركاء ونسب الأرباح ومسحوباتهم.

import sqlite3
from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from datetime import datetime
from database import get_db_conn
from auth import has_perm, get_entity

partners_bp = Blueprint('partners', __name__)

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

@partners_bp.route('/partners', methods=['GET', 'POST'])
def partners_page():
    if not has_perm('part', 'v'):
        flash('غير مصرح لك بالوصول لصفحة الشركاء!', 'error')
        return redirect(url_for('auth.dashboard'))
    
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    if request.method == 'POST':
        if not has_perm('part', 'a'): 
            return redirect(url_for('partners.partners_page'))
            
        name = request.form['name']
        phone = request.form['phone']
        profit_share = parse_profit_share(request.form.get('profit_share', '100'))
        
        cursor.execute("INSERT INTO partners (name, phone, profit_share, entity_id) VALUES (?, ?, ?, ?)", 
                       (name, phone, profit_share, real_entity))
        conn.commit()
        conn.close()
        return redirect(url_for('partners.partners_page'))
    
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

@partners_bp.route('/add_withdrawal', methods=['POST'])
def add_withdrawal():
    if not has_perm('part', 'a'): 
        return redirect(url_for('partners.partners_page'))
        
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
        return redirect(url_for('partners.partners_page'))
        
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
        return redirect(url_for('partners.partners_page'))

    cursor.execute("INSERT INTO partner_withdrawals (partner_id, amount, notes, entity_id) VALUES (?, ?, ?, ?)", 
                   (partner_id, amount, notes, real_entity))
    conn.commit()
    conn.close()
    flash('تم تسجيل تسليم الأرباح بنجاح!', 'success')
    return redirect(url_for('partners.partners_page'))

@partners_bp.route('/edit_withdrawal', methods=['POST'])
def edit_withdrawal():
    if not has_perm('part', 'e'): 
        return redirect(url_for('partners.partners_page'))
        
    withdrawal_id = request.form['withdrawal_id']
    amount = float(request.form['amount'])
    notes = request.form.get('notes', '')
    
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE partner_withdrawals SET amount=?, notes=? WHERE id=?", (amount, notes, withdrawal_id))
    conn.commit()
    conn.close()
    flash('تم التعديل!', 'success')
    return redirect(url_for('partners.partners_page'))

@partners_bp.route('/delete_withdrawal/<int:withdrawal_id>')
def delete_withdrawal(withdrawal_id):
    if not has_perm('part', 'd'): 
        return redirect(url_for('partners.partners_page'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM partner_withdrawals WHERE id=?", (withdrawal_id,))
    conn.commit()
    conn.close()
    flash('تم حذف عملية السحب.', 'success')
    return redirect(url_for('partners.partners_page'))

@partners_bp.route('/edit_partner', methods=['POST'])
def edit_partner():
    if not has_perm('part', 'e'): 
        return redirect(url_for('partners.partners_page'))
        
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
    return redirect(url_for('partners.partners_page'))

@partners_bp.route('/delete_partner/<int:id>')
def delete_partner(id):
    if not has_perm('part', 'd'): 
        return redirect(url_for('partners.partners_page'))
        
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
    return redirect(url_for('partners.partners_page'))