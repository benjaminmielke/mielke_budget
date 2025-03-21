import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from datetime import datetime, date
import os
import calendar
import uuid
from dateutil.relativedelta import relativedelta

# ─────────────────────────────────────────────────────────────────────────────
# 0) Query Parameter Fallback Functions
# ─────────────────────────────────────────────────────────────────────────────
def get_query_params_fallback():
    if hasattr(st, "query_params"):
        return st.query_params
    else:
        return st.experimental_get_query_params()

def set_query_params_fallback(**kwargs):
    if not kwargs:
        if hasattr(st, "set_query_params"):
            st.set_query_params()
        else:
            st.experimental_set_query_params()
    else:
        if hasattr(st, "set_query_params"):
            st.set_query_params(**kwargs)
        else:
            st.experimental_set_query_params(**kwargs)

# ─────────────────────────────────────────────────────────────────────────────
# 1) Session State Initialization
# ─────────────────────────────────────────────────────────────────────────────
if "show_new_category_form" not in st.session_state:
    st.session_state["show_new_category_form"] = False
if "show_new_item_form" not in st.session_state:
    st.session_state["show_new_item_form"] = False
if "temp_new_category" not in st.session_state:
    st.session_state["temp_new_category"] = ""
if "temp_new_item" not in st.session_state:
    st.session_state["temp_new_item"] = ""

if "editing_budget_item" not in st.session_state:
    st.session_state["editing_budget_item"] = None
if "temp_budget_edit_date" not in st.session_state:
    st.session_state["temp_budget_edit_date"] = datetime.today()
if "temp_budget_edit_amount" not in st.session_state:
    st.session_state["temp_budget_edit_amount"] = 0.0

if "editing_debt_item" not in st.session_state:
    st.session_state["editing_debt_item"] = None
if "temp_new_balance" not in st.session_state:
    st.session_state["temp_new_balance"] = 0.0

if "current_month" not in st.session_state:
    st.session_state["current_month"] = datetime.today().month
if "current_year" not in st.session_state:
    st.session_state["current_year"] = datetime.today().year

if "active_payoff_plan" not in st.session_state:
    st.session_state["active_payoff_plan"] = None
if "temp_payoff_date" not in st.session_state:
    st.session_state["temp_payoff_date"] = datetime.today().date()

# ─────────────────────────────────────────────────────────────────────────────
# 2) Custom CSS for Layout, Metrics, and Calendar Styling
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Container for top metrics */
.metrics-container {
    background: #222;
    border-radius: 8px;
    padding: 10px;
    margin: 10px auto;
    max-width: 800px;
    display: flex;
    justify-content: center;
    gap: 8px;
}

/* Each individual metric box */
.metric-box {
    background-color: #333;
    padding: 8px 10px;
    border-radius: 8px;
    text-align: center;
    font-size: 14px;
    color: #fff;
}

/* Background bar for the line item info */
.line-item-info {
    background-color: #333;
    border-radius: 5px;
    padding: 8px;
    color: #fff;
    font-size: 14px;
    white-space: nowrap;
}

/* Custom button styles for edit and delete */
.custom-btn {
    background-color: #555;
    color: #fff;
    border: none;
    border-radius: 3px;
    padding: 6px 12px;
    font-size: 12px;
    cursor: pointer;
    margin-left: 8px;
}
.custom-btn:hover {
    opacity: 0.8;
}
.custom-btn.delete {
    background-color: #900;
}

/* Stylized calendar container */
.calendar-container {
    overflow-x: auto;
    max-width: 800px;
    margin: 20px auto;
    background-color: #222;
    border-radius: 8px;
    padding: 10px;
}
.calendar-container table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    color: #fff;
}
.calendar-container th, .calendar-container td {
    border: 1px solid #444;
    padding: 8px;
    text-align: center;
}
.calendar-container th {
    background-color: #333;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# 3) Google Cloud & BigQuery Setup using Streamlit Secrets
# ─────────────────────────────────────────────────────────────────────────────
bigquery_secrets = st.secrets["bigquery"]
credentials = service_account.Credentials.from_service_account_info(bigquery_secrets)
PROJECT_ID = bigquery_secrets["project_id"]
DATASET_ID = "budget_data"

CATS_TABLE_NAME = "dimension_budget_categories"
FACT_TABLE_NAME = "fact_budget_inputs"
DEBT_TABLE_NAME = "fact_debt_items"

client = bigquery.Client(credentials=credentials, project=PROJECT_ID)

# ─────────────────────────────────────────────────────────────────────────────
# 4) Dimension Table Functions (Categories/Items)
# ─────────────────────────────────────────────────────────────────────────────
def load_dimension_rows(type_val):
    query = f"""
    SELECT rowid, type, category, budget_item
    FROM `{PROJECT_ID}.{DATASET_ID}.{CATS_TABLE_NAME}`
    WHERE LOWER(type) = LOWER('{type_val}')
    """
    return client.query(query).to_dataframe()

def add_dimension_row(type_val, category_val, budget_item_val):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{CATS_TABLE_NAME}"
    capital_type = type_val.capitalize()
    df = pd.DataFrame([{
        "rowid": str(uuid.uuid4()),
        "type": capital_type,
        "category": category_val,
        "budget_item": budget_item_val
    }])
    job = client.load_table_from_dataframe(df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"))
    job.result()

# ─────────────────────────────────────────────────────────────────────────────
# 5) Fact Table Functions (Budget Planning)
# ─────────────────────────────────────────────────────────────────────────────
def load_fact_data():
    query = f"SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.{FACT_TABLE_NAME}`"
    df = client.query(query).to_dataframe()
    df['date'] = pd.to_datetime(df['date'])
    return df

def save_fact_data(rows_df):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{FACT_TABLE_NAME}"
    job = client.load_table_from_dataframe(rows_df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"))
    job.result()

def remove_fact_row(row_id):
    query = f"""
    DELETE FROM `{PROJECT_ID}.{DATASET_ID}.{FACT_TABLE_NAME}`
    WHERE rowid = '{row_id}'
    """
    client.query(query).result()

def update_fact_row(row_id, new_date, new_amount):
    date_str = new_date.strftime("%Y-%m-%d")
    query = f"""
    UPDATE `{PROJECT_ID}.{DATASET_ID}.{FACT_TABLE_NAME}`
    SET date = '{date_str}', amount = {new_amount}
    WHERE rowid = '{row_id}'
    """
    client.query(query).result()

def remove_old_payoff_lines_for_debt(debt_name):
    escaped_name = debt_name.replace("'", "''")
    query = f"""
    DELETE FROM `{PROJECT_ID}.{DATASET_ID}.{FACT_TABLE_NAME}`
    WHERE type='expense'
      AND category='Debt Payment'
      AND budget_item='{escaped_name}'
      AND note='Auto Payoff Plan'
    """
    client.query(query).result()

# ─────────────────────────────────────────────────────────────────────────────
# 6) Debt Domination Table Functions
# ─────────────────────────────────────────────────────────────────────────────
def load_debt_items():
    query = f"SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.{DEBT_TABLE_NAME}`"
    df = client.query(query).to_dataframe()
    if "payoff_plan_date" in df.columns:
        df["payoff_plan_date"] = pd.to_datetime(df["payoff_plan_date"]).dt.date
    return df

def add_debt_item(debt_name, current_balance, due_date, min_payment):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{DEBT_TABLE_NAME}"
    if due_date == "(None)":
        due_date = None
    min_payment_val = None
    if min_payment.strip():
        try:
            min_payment_val = float(min_payment)
        except:
            min_payment_val = None
    df = pd.DataFrame([{
        "rowid": str(uuid.uuid4()),
        "debt_name": debt_name,
        "current_balance": current_balance,
        "due_date": due_date,
        "minimum_payment": min_payment_val,
        "payoff_plan_date": None
    }])
    job = client.load_table_from_dataframe(df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"))
    job.result()

def remove_debt_item(row_id):
    query = f"""
    DELETE FROM `{PROJECT_ID}.{DATASET_ID}.{DEBT_TABLE_NAME}`
    WHERE rowid = '{row_id}'
    """
    client.query(query).result()

def update_debt_item(row_id, new_balance):
    query = f"""
    UPDATE `{PROJECT_ID}.{DATASET_ID}.{DEBT_TABLE_NAME}`
    SET current_balance = {new_balance}
    WHERE rowid = '{row_id}'
    """
    client.query(query).result()

def update_debt_payoff_plan_date(row_id, new_date):
    if new_date is None:
        query = f"""
        UPDATE `{PROJECT_ID}.{DATASET_ID}.{DEBT_TABLE_NAME}`
        SET payoff_plan_date = NULL
        WHERE rowid = '{row_id}'
        """
    else:
        date_str = new_date.strftime("%Y-%m-%d")
        query = f"""
        UPDATE `{PROJECT_ID}.{DATASET_ID}.{DEBT_TABLE_NAME}`
        SET payoff_plan_date = '{date_str}'
        WHERE rowid = '{row_id}'
        """
    client.query(query).result()

def insert_monthly_payments_for_debt(debt_name, total_balance, debt_due_date_str, payoff_date):
    remove_old_payoff_lines_for_debt(debt_name)
    digits = "".join(ch for ch in (debt_due_date_str or "") if ch.isdigit())
    day_of_month = 1
    if digits:
        try:
            day_of_month = int(digits)
        except:
            day_of_month = 1
    today_dt = datetime.today().date()
    if payoff_date <= today_dt:
        return
    start_year = today_dt.year
    start_month = today_dt.month
    payoff_year = payoff_date.year
    payoff_month = payoff_date.month
    months_list = []
    y, m = start_year, start_month
    while (y < payoff_year) or (y == payoff_year and m <= payoff_month):
        last_day = calendar.monthrange(y, m)[1]
        actual_day = min(day_of_month, last_day)
        dt_candidate = date(y, m, actual_day)
        if dt_candidate >= today_dt:
            months_list.append(dt_candidate)
        m += 1
        if m > 12:
            m = 1
            y += 1
    if not months_list:
        return
    monthly_amount = round(total_balance / len(months_list), 2)
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{FACT_TABLE_NAME}"
    rows_to_insert = []
    for d in months_list:
        new_row_id = str(uuid.uuid4())
        rows_to_insert.append({
            "rowid": new_row_id,
            "date": d,
            "type": "expense",
            "amount": monthly_amount,
            "category": "Debt Payment",
            "budget_item": debt_name,
            "credit_card": None,
            "note": "Auto Payoff Plan"
        })
    if rows_to_insert:
        df = pd.DataFrame(rows_to_insert)
        job = client.load_table_from_dataframe(df, table_id,
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"))
        job.result()

# ─────────────────────────────────────────────────────────────────────────────
# 7) Query Parameter Processing
params = get_query_params_fallback()
if "action" in params and "rowid" in params:
    action = params["action"][0] if isinstance(params["action"], list) else params["action"]
    row_id = params["rowid"][0] if isinstance(params["rowid"], list) else params["rowid"]
    if action == "remove":
        remove_fact_row(row_id)
        set_query_params_fallback()
        st.experimental_rerun()
    elif action == "edit":
        st.session_state["editing_budget_item"] = row_id
        set_query_params_fallback()
        st.experimental_rerun()

if "recalc" in params:
    row_id = params["recalc"]
    if isinstance(row_id, list):
        row_id = row_id[0]
    reloaded_df = load_debt_items()
    match = reloaded_df[reloaded_df["rowid"] == row_id]
    if not match.empty:
        plan_data = match.iloc[0]
        plan_name = plan_data["debt_name"]
        plan_balance = plan_data["current_balance"]
        plan_due = plan_data["due_date"] if plan_data["due_date"] else ""
        plan_existing = plan_data["payoff_plan_date"] if plan_data["payoff_plan_date"] else datetime.today().date()
        insert_monthly_payments_for_debt(plan_name, plan_balance, plan_due, plan_existing)
    set_query_params_fallback()
    st.experimental_rerun()

if "payoff" in params:
    row_id = params["payoff"]
    if isinstance(row_id, list):
        row_id = row_id[0]
    st.session_state["active_payoff_plan"] = row_id
    set_query_params_fallback()
    st.experimental_rerun()

# ─────────────────────────────────────────────────────────────────────────────
# 8) Sidebar Navigation
st.sidebar.title("Mielke Finances")
page_choice = st.sidebar.radio("Navigation", ["Budget Planning", "Debt Domination", "Budget Overview"])

# ─────────────────────────────────────────────────────────────────────────────
# Helper functions to render transaction and debt rows with a background bar for info only

def render_transaction_row(row, color_class):
    row_id = row["rowid"]
    date_str = row["date"].strftime("%Y-%m-%d")
    item_str = row["budget_item"]
    amount_str = f"${row['amount']:,.2f}"
    # Use three columns: info, Edit button, Delete button.
    cols = st.columns([4, 1, 1])
    with cols[0]:
        st.markdown(f"""
        <div class="line-item-info">
            <span style="font-weight:bold;">{date_str}</span>
            <span>{item_str}</span>
            <span style="color:{color_class};">{amount_str}</span>
        </div>
        """, unsafe_allow_html=True)
    with cols[1]:
        if st.button("Edit", key=f"edit_{row_id}"):
            st.session_state["editing_budget_item"] = row_id
            st.experimental_rerun()
    with cols[2]:
        if st.button("❌", key=f"delete_{row_id}"):
            remove_fact_row(row_id)
            st.experimental_rerun()

def render_debt_transaction_row(row):
    row_id = row["rowid"]
    name = row["debt_name"]
    balance_str = f"${row['current_balance']:,.2f}"
    due = row["due_date"] if row["due_date"] else "(None)"
    min_pay = row["minimum_payment"] if pd.notnull(row["minimum_payment"]) else "(None)"
    cols = st.columns([4, 1, 1])
    with cols[0]:
        st.markdown(f"""
        <div class="line-item-info">
            <span>{name}</span>
            <span>Due: {due}, Min: {min_pay}</span>
            <span style="color:red;">{balance_str}</span>
        </div>
        """, unsafe_allow_html=True)
    with cols[1]:
        if st.button("Edit", key=f"edit_debt_{row_id}"):
            st.session_state["editing_debt_item"] = row_id
            st.experimental_rerun()
    with cols[2]:
        if st.button("❌", key=f"delete_debt_{row_id}"):
            remove_debt_item(row_id)
            remove_old_payoff_lines_for_debt(name)
            st.experimental_rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 1: Budget Planning
if page_choice == "Budget Planning":
    st.markdown("""
        <h1 style='text-align: center; font-size: 50px; font-weight: bold; 
                   color: black; text-shadow: 0px 0px 10px #00ccff, 
                                 0px 0px 20px #00ccff;'>
            Mielke Budget
        </h1>
    """, unsafe_allow_html=True)
    current_month = st.session_state["current_month"]
    current_year = st.session_state["current_year"]
    st.markdown(f"<div style='text-align: center; font-size: 24px; font-weight: bold; padding: 10px;'>{calendar.month_name[current_month]} {current_year}</div>", unsafe_allow_html=True)
    
    col_prev, col_next = st.columns(2)
    with col_prev:
        if st.button("Previous Month"):
            if current_month == 1:
                st.session_state["current_month"] = 12
                st.session_state["current_year"] -= 1
            else:
                st.session_state["current_month"] -= 1
            st.experimental_rerun()
    with col_next:
        if st.button("Next Month"):
            if current_month == 12:
                st.session_state["current_month"] = 1
                st.session_state["current_year"] += 1
            else:
                st.session_state["current_month"] += 1
            st.experimental_rerun()
    
    fact_data = load_fact_data()
    fact_data.sort_values("date", ascending=True, inplace=True)
    filtered_data = fact_data[
        (fact_data["date"].dt.month == current_month) &
        (fact_data["date"].dt.year == current_year)
    ].copy()
    total_income = filtered_data[filtered_data["type"]=="income"]["amount"].sum()
    total_expenses = filtered_data[filtered_data["type"]=="expense"]["amount"].sum()
    leftover = total_income - total_expenses
    
    st.markdown(f"""
    <div class="metrics-container">
        <div class="metric-box">
            <div>Total Income</div>
            <div style='color:green;'>{total_income:,.2f}</div>
        </div>
        <div class="metric-box">
            <div>Total Expenses</div>
            <div style='color:red;'>{total_expenses:,.2f}</div>
        </div>
        <div class="metric-box">
            <div>Leftover</div>
            <div style='color:{"green" if leftover>=0 else "red"};'>{leftover:,.2f}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Stylized Calendar
    days_in_month = calendar.monthrange(current_year, current_month)[1]
    first_weekday = (calendar.monthrange(current_year, current_month)[0] + 1) % 7
    calendar_grid = [["" for _ in range(7)] for _ in range(6)]
    day_counter = 1
    for week in range(6):
        for weekday in range(7):
            if week == 0 and weekday < first_weekday:
                continue
            if day_counter > days_in_month:
                break
            cell_html = f"<strong>{day_counter}</strong>"
            day_tx = filtered_data[filtered_data["date"].dt.day == day_counter]
            for _, row in day_tx.iterrows():
                color = "red" if row["type"]=="expense" else "green"
                cell_html += f"<br><span style='color:{color};'>{row['amount']:,.2f}<br>({row['budget_item']})</span>"
            calendar_grid[week][weekday] = cell_html
            day_counter += 1
    cal_df = pd.DataFrame(calendar_grid, columns=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"])
    st.markdown(f'<div class="calendar-container">{cal_df.to_html(index=False, escape=False)}</div>', unsafe_allow_html=True)
    
    st.markdown("<div class='section-subheader'>Add New Income/Expense</div>", unsafe_allow_html=True)
    cA, cB = st.columns([1,3])
    with cA:
        st.write("Date:")
    with cB:
        date_input = st.date_input("", value=datetime.today(), label_visibility="collapsed")
    cA, cB = st.columns([1,3])
    with cA:
        st.write("Type:")
    with cB:
        type_input = st.selectbox("", ["income","expense"], label_visibility="collapsed")
    dimension_df = load_dimension_rows(type_input)
    all_categories = sorted(dimension_df["category"].unique())
    if not all_categories:
        all_categories = ["(No categories yet)"]
    cA, cB = st.columns([1,2.8])
    with cA:
        st.write("Category:")
    with cB:
        cat_left, cat_plus = st.columns([0.9,0.1])
        with cat_left:
            category_input = st.selectbox("", all_categories, label_visibility="collapsed")
        with cat_plus:
            if st.button("➕", key="cat_plus"):
                st.session_state["show_new_category_form"] = True
    if st.session_state["show_new_category_form"]:
        st.write("Add New Category")
        st.session_state["temp_new_category"] = st.text_input("Category Name", st.session_state["temp_new_category"])
        cc1, cc2 = st.columns(2)
        if cc1.button("Save Category"):
            new_cat = st.session_state["temp_new_category"].strip()
            if new_cat:
                add_dimension_row(type_input, new_cat, "")
            st.session_state["show_new_category_form"] = False
            st.session_state["temp_new_category"] = ""
            st.experimental_rerun()
        if cc2.button("Cancel"):
            st.session_state["show_new_category_form"] = False
            st.session_state["temp_new_category"] = ""
    items_for_cat = dimension_df[dimension_df["category"]==category_input]["budget_item"].unique()
    items_for_cat = [i for i in items_for_cat if i!=""]
    if not items_for_cat:
        items_for_cat = ["(No items yet)"]
    cA, cB = st.columns([1,2.8])
    with cA:
        st.write("Budget Item:")
    with cB:
        item_left, item_plus = st.columns([0.9,0.1])
        with item_left:
            budget_item_input = st.selectbox("", items_for_cat, label_visibility="collapsed")
        with item_plus:
            if st.button("➕", key="item_plus"):
                st.session_state["show_new_item_form"] = True
    if st.session_state["show_new_item_form"]:
        st.write(f"Add New Item for Category: {category_input}")
        st.session_state["temp_new_item"] = st.text_input("New Budget Item", st.session_state["temp_new_item"])
        ic1, ic2 = st.columns(2)
        if ic1.button("Save Item"):
            new_item = st.session_state["temp_new_item"].strip()
            if new_item:
                add_dimension_row(type_input, category_input, new_item)
            st.session_state["show_new_item_form"] = False
            st.session_state["temp_new_item"] = ""
            st.experimental_rerun()
        if ic2.button("Cancel"):
            st.session_state["show_new_item_form"] = False
            st.session_state["temp_new_item"] = ""
    cA, cB = st.columns([1,3])
    with cA:
        st.write("Amount:")
    with cB:
        amount_input = st.number_input("", min_value=0.0, format="%.2f", label_visibility="collapsed")
    cA, cB = st.columns([1,3])
    with cA:
        st.write("Note:")
    with cB:
        note_input = st.text_area("", label_visibility="collapsed")
    cX, cY = st.columns([1,3])
    with cY:
        if st.button("Add Transaction"):
            row_id = str(uuid.uuid4())
            tx_df = pd.DataFrame([{
                "rowid": row_id,
                "date": date_input,
                "type": type_input,
                "amount": amount_input,
                "category": category_input,
                "budget_item": budget_item_input,
                "credit_card": None,
                "note": note_input
            }])
            save_fact_data(tx_df)
            st.experimental_rerun()
            
    st.markdown("<div class='section-subheader'>Transactions This Month</div>", unsafe_allow_html=True)
    if filtered_data.empty:
        st.write("No transactions found for this month.")
    else:
        if st.session_state["editing_budget_item"]:
            match = filtered_data[filtered_data["rowid"] == st.session_state["editing_budget_item"]]
            if not match.empty:
                st.info("Editing functionality triggered – please complete the edit form.")
        else:
            inc_data = filtered_data[filtered_data["type"]=="income"]
            exp_data = filtered_data[filtered_data["type"]=="expense"]
            if not inc_data.empty:
                for cat_name, group_df in inc_data.groupby("category"):
                    st.markdown(f"<div style='color:#fff; font-weight:bold;'>{cat_name}</div>", unsafe_allow_html=True)
                    for _, row in group_df.iterrows():
                        render_transaction_row(row, "#00cc00")
            if not exp_data.empty:
                for cat_name, group_df in exp_data.groupby("category"):
                    st.markdown(f"<div style='color:#fff; font-weight:bold;'>{cat_name}</div>", unsafe_allow_html=True)
                    for _, row in group_df.iterrows():
                        render_transaction_row(row, "#ff4444")
                        
elif page_choice == "Debt Domination":
    st.markdown("""
        <h1 style='text-align: center; font-size: 50px; font-weight: bold; color: black;
                   text-shadow: 0px 0px 10px #00ccff, 0px 0px 20px #00ccff;'>
            Debt Domination
        </h1>
    """, unsafe_allow_html=True)
    debt_df = load_debt_items()
    total_debt = debt_df["current_balance"].sum() if not debt_df.empty else 0.0
    st.markdown(f"""
    <div style='display: flex; justify-content: center; text-align: center; padding:10px 0;'>
        <div class="metric-box">
            <div>Total Debt</div>
            <div style='color:red;'>{total_debt:,.2f}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.subheader("Your Debts")
    if debt_df.empty:
        st.write("No debt items found.")
    else:
        for idx, row in debt_df.iterrows():
            render_debt_transaction_row(row)
    if st.session_state["active_payoff_plan"] is not None:
        reloaded_df = load_debt_items()
        match = reloaded_df[reloaded_df["rowid"]==st.session_state["active_payoff_plan"]]
        if not match.empty:
            plan_data = match.iloc[0]
            plan_name = plan_data["debt_name"]
            plan_balance = plan_data["current_balance"]
            plan_due = plan_data["due_date"] if plan_data["due_date"] else ""
            st.markdown("<hr>", unsafe_allow_html=True)
            st.subheader(f"Payoff Plan for {plan_name}")
            st.session_state["temp_payoff_date"] = st.date_input(
                "What date do you want to pay this off by?",
                value=st.session_state["temp_payoff_date"]
            )
            pay_col, cancel_col = st.columns(2)
            if pay_col.button("Submit"):
                insert_monthly_payments_for_debt(
                    plan_name,
                    plan_balance,
                    plan_due,
                    st.session_state["temp_payoff_date"]
                )
                date_str = st.session_state["temp_payoff_date"].strftime("%Y-%m-%d")
                query = f"""
                UPDATE `{PROJECT_ID}.{DATASET_ID}.{DEBT_TABLE_NAME}`
                SET payoff_plan_date = '{date_str}'
                WHERE rowid = '{st.session_state["active_payoff_plan"]}'
                """
                client.query(query).result()
                st.session_state["active_payoff_plan"] = None
                st.experimental_rerun()
            if cancel_col.button("Cancel"):
                st.session_state["active_payoff_plan"] = None
                st.experimental_rerun()
    st.subheader("Add a New Debt Item")
    new_debt_name = st.text_input("Debt Name (e.g. 'Loft Credit Card')", "")
    new_debt_balance = st.number_input("Current Balance", min_value=0.0, format="%.2f", value=0.0)
    due_date_options = ["(None)"] + [f"{d}st" if d==1 else f"{d}nd" if d==2 else f"{d}rd" if d==3 else f"{d}th" for d in range(1,32)]
    new_due_date = st.selectbox("Due Date (Optional)", due_date_options, index=0)
    new_min_payment = st.text_input("Minimum Payment (Optional, blank=none)")
    if st.button("Add Debt"):
        if new_debt_name.strip():
            add_debt_item(new_debt_name.strip(), new_debt_balance, new_due_date, new_min_payment)
        st.experimental_rerun()
        
elif page_choice == "Budget Overview":
    st.markdown("""
        <h1 style='text-align: center; font-size: 50px; font-weight: bold;
                   color: black; text-shadow: 0px 0px 10px #00ccff,
                                 0px 0px 20px #00ccff;'>
            Budget Overview
        </h1>
    """, unsafe_allow_html=True)
    today = datetime.today()
    first_of_this_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_date = first_of_this_month
    end_date = first_of_this_month + relativedelta(months=12) - relativedelta(days=1)
    fact_data = load_fact_data()
    fact_data["date"] = pd.to_datetime(fact_data["date"])
    mask = (fact_data["date"]>=start_date) & (fact_data["date"]<=end_date)
    data_12mo = fact_data[mask].copy()
    total_inc_12 = data_12mo[data_12mo["type"]=="income"]["amount"].sum()
    total_exp_12 = data_12mo[data_12mo["type"]=="expense"]["amount"].sum()
    leftover_12 = total_inc_12 - total_exp_12
    st.markdown(f"""
    <div style='display: flex; justify-content: center; gap: 8px; padding: 10px 0;'>
        <div class="metric-box">
            <div>12-Month Income</div>
            <div style='color:green;'>{total_inc_12:,.2f}</div>
        </div>
        <div class="metric-box">
            <div>12-Month Expenses</div>
            <div style='color:red;'>{total_exp_12:,.2f}</div>
        </div>
        <div class="metric-box">
            <div>Leftover</div>
            <div style='color:{"green" if leftover_12>=0 else "red"};'>{leftover_12:,.2f}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    data_12mo["year_month"] = data_12mo["date"].dt.to_period("M")
    monthly_sums = data_12mo.groupby(["year_month","type"])["amount"].sum().reset_index()
    monthly_cat = data_12mo.groupby(["year_month","type","category"])["amount"].sum().reset_index()
    monthly_sums.sort_values("year_month", inplace=True)
    monthly_cat.sort_values(["year_month","type","category"], inplace=True)
    unique_months = monthly_sums["year_month"].drop_duplicates().sort_values()
    for ym in unique_months:
        y = ym.year
        m = ym.month
        m_name = calendar.month_name[m]
        display_str = f"{m_name} {y}"
        inc_val = monthly_sums[(monthly_sums["year_month"]==ym)&(monthly_sums["type"]=="income")]["amount"].sum()
        exp_val = monthly_sums[(monthly_sums["year_month"]==ym)&(monthly_sums["type"]=="expense")]["amount"].sum()
        leftover_val = inc_val - exp_val
        st.markdown(f"""
        <div style="margin-top:20px; padding:5px; background-color:#222; border-radius:5px;">
            <h3 style="color:#66ccff; margin:5px 0;">{display_str}</h3>
            <div style="display:flex; justify-content: center; gap: 8px;">
                <div>
                    <span style="color:green; font-weight:bold;">Income:</span> ${inc_val:,.2f}
                </div>
                <div>
                    <span style="color:red; font-weight:bold;">Expenses:</span> ${exp_val:,.2f}
                </div>
                <div>
                    <span style="color:{'green' if leftover_val>=0 else 'red'}; font-weight:bold;">
                        Leftover: ${leftover_val:,.2f}
                    </span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        mo_details = monthly_cat[monthly_cat["year_month"]==ym].copy()
        if mo_details.empty:
            st.write("No transactions for this month.")
        else:
            inc_cats = mo_details[mo_details["type"]=="income"]
            exp_cats = mo_details[mo_details["type"]=="expense"]
            if not inc_cats.empty:
                st.markdown("<b>Income Categories:</b>", unsafe_allow_html=True)
                for _, row in inc_cats.iterrows():
                    cat_name = row["category"]
                    amt = row["amount"]
                    st.write(f" - {cat_name}: ${amt:,.2f}")
            if not exp_cats.empty:
                st.markdown("<b>Expense Categories:</b>", unsafe_allow_html=True)
                for _, row in exp_cats.iterrows():
                    cat_name = row["category"]
                    amt = row["amount"]
                    st.write(f" - {cat_name}: ${amt:,.2f}")
    st.markdown("<hr>", unsafe_allow_html=True)
    st.write("End of 12-month Forward Budget Overview")
