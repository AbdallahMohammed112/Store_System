# هذا الملف مسئول عن تسجيل وعرض المصروفات اليومية.

import sqlite3
from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from datetime import datetime
from database import get_db_conn
from auth import has_perm, get_entity

expenses_bp = Blueprint('expenses', __name__)

@expenses_bp.route('/expenses', methods=['GET', 'POST'])
def expenses_page():
    if not has_perm('exp', 'v'):
        flash('غير مصرح لك بإدارة المصروفات!', 'error')
        return redirect(url_for('auth.dashboard'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    entity = get_entity()
    real_entity = entity if entity != 'all' else 1
    
    if request.method == 'POST':
        if not has_perm('exp', 'a'): 
            return redirect(url_for('expenses.expenses_page'))
            
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
        return redirect(url_for('expenses.expenses_page'))
    
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

@expenses_bp.route('/delete_expense/<int:expense_id>')
def delete_expense(expense_id):
    if not has_perm('exp', 'd'): 
        return redirect(url_for('expenses.expenses_page'))
        
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('expenses.expenses_page'))