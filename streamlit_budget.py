import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from datetime import datetime, date
import calendar
import uuid
from dateutil.relativedelta import relativedelta

# =============================================================================
# Custom CSS to style the dark bar and adjust for mobile
# =============================================================================
st.markdown("""
<style>
/* Prevent st.columns from wrapping */
[data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important;
}

/* Dark bar styling for each row */
.dark-bar {
  background-color: #333;
  padding: 10px;
  border-radius: 5px;
  margin-bottom: 8px;
  width: 100%;
}

/* Ensure text in the bar is kept in one line */
.dark-bar span {
  white-space: nowrap;
}

/* Styling for metric boxes */
.metric-box {
  background-color: #333;
  padding: 10px 15px;
  border-radius: 10px;
  margin: 5px;
  text-align: center;
}

/* Mobile adjustments */
@media only screen and (max-width: 600px) {
  .dark-bar {
    padding: 5px;
    font-size: 14px;
    max-width: 400px;   /* Limit the dark bar's width */
    margin-left: auto;
    margin-right: auto;
  }
  [data-testid="stHorizontalBlock"] > div {
    padding: 2px !important;
    margin: 2px !important;
  }
  .row-button {
    padding: 2px 4px !important;
    font-size: 10px !important;
    margin-left: 2px !important;
  }
  .metric-box {
    font-size: 12px;
    padding: 5px 8px;
  }
  .calendar-container table {
    font-size: 12px;
  }
}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# Session State Initialization
# =============================================================================
if "editing_budget_item" not in st.session_state:
    st.session_state.editing_budget_item = None
if "temp_budget_edit_date" not in st.session_state:
    st.session_state.temp_budget_edit_date = datetime.today()
if "temp_budget_edit_amount" not in st.session_state:
    st.session_state.temp_budget_edit_amount = 0.0

if "editing_debt_item" not in st.session_state:
    st.session_state.editing_debt_item = None
if "temp_new_balance" not in st.session_state:
    st.session_state.temp_new_balance = 0.0

if "current_month" not in st.session_state:
    st.session_state.current_month = datetime.today().month
if "current_year" not in st.session_state:
    st.session_state.current_year = datetime.today().year

if "active_payoff_plan" not in st.session_state:
    st.session_state.active_payoff_plan = None
if "temp_payoff_date" not in st.session_state:
    st.session_state.temp_payoff_date = datetime.today().date()

if "show_new_category_form" not in st.session_state:
    st.session_state.show_new_category_form = False
if "show_new_item_form" not in st.session_state:
    st.session_state.show_new_item_form = False
if "temp_new_category" not in st.session_state:
    st.session_state.temp_new_category = ""
if "temp_new_item" not in st.session_state:
    st.session_state.temp_new_item = ""

# =============================================================================
# BigQuery Setup (using st.secrets)
# =============================================================================
bigquery_secrets = st.secrets["bigquery"]
credentials = service_account.Credentials.from_service_account_info(bigquery_secrets)
PROJECT_ID = bigquery_secrets["project_id"]
DATASET_ID = "budget_data"
CATS_TABLE_NAME = "dimension_budget_categories"
FACT_TABLE_NAME = "fact_budget_inputs"
DEBT_TABLE_NAME = "fact_debt_items"
client = bigquery.Client(credentials=credentials, project=PROJECT_ID)

# =============================================================================
# Database Functions
# =============================================================================
def load_fact_data():
    query = f"SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.{FACT_TABLE_NAME}`"
    df = client.query(query).to_dataframe()
    df['date'] = pd.to_datetime(df['date'])
    return df

def save_fact_data(rows_df):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{FACT_TABLE_NAME}"
    job = client.load_table_from_dataframe(
        rows_df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    )
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

def load_debt_items():
    query = f"SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.{DEBT_TABLE_NAME}`"
    df = client.query(query).to_dataframe()
    if "payoff_plan_date" in df.columns:
        df["payoff_plan_date"] = pd.to_datetime(df["payoff_plan_date"]).dt.date
    return df

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

def insert_monthly_payments_for_debt(debt_name, total_balance, debt_due_date_str, payoff_date):
    escaped_name = debt_name.replace("'", "''")
    query = f"""
    DELETE FROM `{PROJECT_ID}.{DATASET_ID}.{FACT_TABLE_NAME}`
    WHERE type='expense'
      AND category='Debt Payment'
      AND budget_item='{escaped_name}'
      AND note='Auto Payoff Plan'
    """
    client.query(query).result()
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
        job = client.load_table_from_dataframe(
            df, table_id,
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
        )
        job.result()

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
    job = client.load_table_from_dataframe(
        df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    )
    job.result()

# =============================================================================
# Row Rendering Functions for Budget Planning using Native Buttons
# =============================================================================
def render_budget_row_html(row, color_class):
    """Render a budget row as a dark bar with native buttons."""
    row_id = row["rowid"]
    date_str = row["date"].strftime("%Y-%m-%d")
    item_str = row["budget_item"]
    amount_str = f"${row['amount']:,.2f}"
    with st.container():
        st.markdown("<div class='dark-bar'>", unsafe_allow_html=True)
        # Use smaller column ratios to reduce width on mobile
        col_date, col_item, col_amt, col_edit, col_remove = st.columns([1, 2, 1, 0.8, 0.8])
        col_date.markdown(f"<span style='color:#fff; font-weight:bold;'>{date_str}</span>", unsafe_allow_html=True)
        col_item.markdown(f"<span style='color:#fff;'>{item_str}</span>", unsafe_allow_html=True)
        col_amt.markdown(f"<span style='color:{color_class};'>{amount_str}</span>", unsafe_allow_html=True)
        if col_edit.button("Edit", key=f"edit_{row_id}"):
            st.session_state.editing_budget_item = row_id
            st.experimental_rerun()
        if col_remove.button("❌", key=f"remove_{row_id}"):
            remove_fact_row(row_id)
            st.experimental_rerun()
        st.markdown("</div>", unsafe_allow_html=True)

def render_budget_row_edit(row, color_class):
    """Render the editing interface for a budget row using native inputs."""
    row_id = row["rowid"]
    item_str = row["budget_item"]
    amount_str = f"${row['amount']:,.2f}"
    st.markdown(f"<div class='dark-bar' style='background-color:#444; color:#fff; font-weight:bold;'>Editing: {item_str} ({amount_str})</div>", unsafe_allow_html=True)
    st.session_state.temp_budget_edit_date = st.date_input("Date", value=row["date"], key=f"edit_date_{row_id}")
    st.session_state.temp_budget_edit_amount = st.number_input("Amount", min_value=0.0, format="%.2f",
                                                               value=float(row["amount"]), key=f"edit_amount_{row_id}")
    col1, col2 = st.columns(2)
    if col1.button("Save", key=f"save_{row_id}"):
        update_fact_row(row_id, st.session_state.temp_budget_edit_date,
                        st.session_state.temp_budget_edit_amount)
        st.session_state.editing_budget_item = None
        st.experimental_rerun()
    if col2.button("Cancel", key=f"cancel_{row_id}"):
        st.session_state.editing_budget_item = None
        st.experimental_rerun()

# =============================================================================
# Row Rendering Functions for Debt Domination using Native Buttons
# =============================================================================
def render_debt_row(row):
    """Render a debt row as a dark bar with native buttons."""
    row_id = row["rowid"]
    row_name = row["debt_name"]
    row_balance = row["current_balance"]
    row_due = row["due_date"] if row["due_date"] else "(None)"
    row_min = row["minimum_payment"] if pd.notnull(row["minimum_payment"]) else "(None)"
    payoff_text = "Recalc" if row.get("payoff_plan_date") else "Payoff"
    with st.container():
        st.markdown("<div class='dark-bar'>", unsafe_allow_html=True)
        col_name, col_info, col_amt, col_edit, col_payoff, col_remove = st.columns([1, 2, 1, 0.8, 0.8, 0.8])
        col_name.markdown(f"<span style='color:#fff; font-weight:bold;'>{row_name}</span>", unsafe_allow_html=True)
        col_info.markdown(f"<span style='color:#fff;'>Due: {row_due}, Min: {row_min}</span>", unsafe_allow_html=True)
        col_amt.markdown(f"<span style='color:red;'>${row_balance:,.2f}</span>", unsafe_allow_html=True)
        if col_edit.button("Edit", key=f"edit_debt_{row_id}"):
            st.session_state.editing_debt_item = row_id
            st.experimental_rerun()
        if col_payoff.button(payoff_text, key=f"payoff_{row_id}"):
            st.session_state.active_payoff_plan = row_id
            st.experimental_rerun()
        if col_remove.button("❌", key=f"remove_debt_{row_id}"):
            remove_debt_item(row_id)
            st.experimental_rerun()
        st.markdown("</div>", unsafe_allow_html=True)

def render_debt_row_edit(row):
    """Render the editing interface for a debt row using native inputs."""
    row_id = row["rowid"]
    row_name = row["debt_name"]
    row_balance = row["current_balance"]
    row_due = row["due_date"] if row["due_date"] else "(None)"
    row_min = row["minimum_payment"] if pd.notnull(row["minimum_payment"]) else "(None)"
    st.markdown(f"<div class='dark-bar' style='background-color:#444; color:#fff; font-weight:bold;'>Editing: {row_name}</div>", unsafe_allow_html=True)
    st.session_state.temp_new_balance = st.number_input("New Balance", min_value=0.0, format="%.2f",
                                                         value=float(row_balance), key=f"edit_debt_balance_{row_id}")
    col1, col2 = st.columns(2)
    if col1.button("Save", key=f"save_debt_{row_id}"):
        update_debt_item(row_id, st.session_state.temp_new_balance)
        st.session_state.editing_debt_item = None
        st.experimental_rerun()
    if col2.button("Cancel", key=f"cancel_debt_{row_id}"):
        st.session_state.editing_debt_item = None
        st.experimental_rerun()

# =============================================================================
# Sidebar & Page Navigation
# =============================================================================
st.sidebar.title("Mielke Finances")
page_choice = st.sidebar.radio("Navigation", ["Budget Planning", "Debt Domination", "Budget Overview"])

# =============================================================================
# Page 1: Budget Planning
# =============================================================================
if page_choice == "Budget Planning":
    st.markdown("""
    <h1 style='text-align: center; font-size: 50px; font-weight: bold; color: black;
    text-shadow: 0px 0px 10px #00ccff, 0px 0px 20px #00ccff;'>Mielke Budget</h1>
    """, unsafe_allow_html=True)
    
    # Month navigation
    nav1, nav2, nav3, nav4 = st.columns([0.25, 1, 2, 1])
    with nav2:
        if st.button("Previous Month"):
            if st.session_state.current_month == 1:
                st.session_state.current_month = 12
                st.session_state.current_year -= 1
            else:
                st.session_state.current_month -= 1
            st.experimental_rerun()
    with nav3:
        st.markdown(f"<div style='text-align: center; font-size: 24px; font-weight: bold; padding: 10px;'>{calendar.month_name[st.session_state.current_month]} {st.session_state.current_year}</div>", unsafe_allow_html=True)
    with nav4:
        if st.button("Next Month"):
            if st.session_state.current_month == 12:
                st.session_state.current_month = 1
                st.session_state.current_year += 1
            else:
                st.session_state.current_month += 1
            st.experimental_rerun()
    
    fact_data = load_fact_data()
    fact_data.sort_values("date", ascending=True, inplace=True)
    filtered_data = fact_data[
        (fact_data["date"].dt.month == st.session_state.current_month) &
        (fact_data["date"].dt.year == st.session_state.current_year)
    ]
    total_income = filtered_data[filtered_data["type"]=="income"]["amount"].sum()
    total_expenses = filtered_data[filtered_data["type"]=="expense"]["amount"].sum()
    leftover = total_income - total_expenses
    
    st.markdown(f"""
    <div style='display: flex; justify-content: space-around; text-align: center; padding: 10px 0;'>
      <div class='metric-box'>
         <div style='font-size:14px; color:#bbb;'>Total Income</div>
         <div style='font-size:20px; font-weight:bold; color:green;'>${total_income:,.2f}</div>
      </div>
      <div class='metric-box'>
         <div style='font-size:14px; color:#bbb;'>Total Expenses</div>
         <div style='font-size:20px; font-weight:bold; color:red;'>${total_expenses:,.2f}</div>
      </div>
      <div class='metric-box'>
         <div style='font-size:14px; color:#bbb;'>Leftover</div>
         <div style='font-size:20px; font-weight:bold; color:{"green" if leftover>=0 else "red"};'>${leftover:,.2f}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    
    days_in_month = calendar.monthrange(st.session_state.current_year, st.session_state.current_month)[1]
    first_weekday = (calendar.monthrange(st.session_state.current_year, st.session_state.current_month)[0] + 1) % 7
    cal_grid = [["" for _ in range(7)] for _ in range(6)]
    d_counter = 1
    for week in range(6):
        for wd in range(7):
            if week == 0 and wd < first_weekday:
                continue
            if d_counter > days_in_month:
                break
            cell = f"<strong>{d_counter}</strong>"
            day_tx = filtered_data[filtered_data["date"].dt.day == d_counter]
            for _, r in day_tx.iterrows():
                clr = "red" if r["type"]=="expense" else "green"
                cell += f"<br><span style='color:{clr};'>${r['amount']:,.2f} ({r['budget_item']})</span>"
            cal_grid[week][wd] = cell
            d_counter += 1
    cal_df = pd.DataFrame(cal_grid, columns=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"])
    st.markdown(f'<div class="calendar-container">{cal_df.to_html(index=False, escape=False)}</div>', unsafe_allow_html=True)
    
    st.markdown("<div class='section-subheader'>Add New Income/Expense</div>", unsafe_allow_html=True)
    date_inp = st.date_input("Date", value=datetime.today(), label_visibility="collapsed")
    type_inp = st.selectbox("Type", ["income", "expense"], label_visibility="collapsed")
    
    dim_df = load_dimension_rows(type_inp)
    cat_list = sorted(dim_df["category"].unique())
    if not cat_list:
        cat_list = ["(No categories yet)"]
    sel_category = st.selectbox("Category", cat_list, key="cat_dropdown")
    if st.button("➕ Add New Category", key="add_category"):
        st.session_state.show_new_category_form = True
    if st.session_state.show_new_category_form:
        new_cat = st.text_input("New Category", key="new_cat_input")
        col_cat1, col_cat2 = st.columns(2)
        if col_cat1.button("Save Category", key="save_category"):
            if new_cat.strip():
                add_dimension_row(type_inp, new_cat.strip(), "")
            st.session_state.show_new_category_form = False
            st.experimental_rerun()
        if col_cat2.button("Cancel", key="cancel_category"):
            st.session_state.show_new_category_form = False
    item_list = dim_df[dim_df["category"] == sel_category]["budget_item"].unique()
    item_list = [i for i in item_list if i != ""]
    if not item_list:
        item_list = ["(No items yet)"]
    sel_budget_item = st.selectbox("Budget Item", item_list, key="budget_item_dropdown")
    if st.button("➕ Add New Budget Item", key="add_budget_item"):
        st.session_state.show_new_item_form = True
    if st.session_state.show_new_item_form:
        new_item = st.text_input("New Budget Item", key="new_item_input")
        col_item1, col_item2 = st.columns(2)
        if col_item1.button("Save Budget Item", key="save_item"):
            if new_item.strip():
                add_dimension_row(type_inp, sel_category, new_item.strip())
            st.session_state.show_new_item_form = False
            st.experimental_rerun()
        if col_item2.button("Cancel", key="cancel_item"):
            st.session_state.show_new_item_form = False
    amt_inp = st.number_input("Amount", min_value=0.0, format="%.2f", label_visibility="collapsed")
    note_inp = st.text_area("Note", label_visibility="collapsed")
    if st.button("Add Transaction"):
        new_id = str(uuid.uuid4())
        new_tx = pd.DataFrame([{
            "rowid": new_id,
            "date": date_inp,
            "type": type_inp,
            "amount": amt_inp,
            "category": sel_category,
            "budget_item": sel_budget_item,
            "credit_card": None,
            "note": note_inp
        }])
        save_fact_data(new_tx)
        st.experimental_rerun()
    
    st.markdown("<div class='section-subheader'>Transactions This Month</div>", unsafe_allow_html=True)
    if filtered_data.empty:
        st.write("No transactions found for this month.")
    else:
        for _, r in filtered_data.iterrows():
            if st.session_state.editing_budget_item == r["rowid"]:
                render_budget_row_edit(r, "#00cc00" if r["type"]=="income" else "#ff4444")
            else:
                render_budget_row_html(r, "#00cc00" if r["type"]=="income" else "#ff4444")

# =============================================================================
# Page 2: Debt Domination
# =============================================================================
elif page_choice == "Debt Domination":
    st.markdown("""
    <h1 style='text-align: center; font-size: 50px; font-weight: bold; color: black;
    text-shadow: 0px 0px 10px #00ccff, 0px 0px 20px #00ccff;'>Debt Domination</h1>
    """, unsafe_allow_html=True)
    debt_df = load_debt_items()
    if debt_df.empty:
        st.write("No debt items found.")
    else:
        for _, r in debt_df.iterrows():
            if st.session_state.editing_debt_item == r["rowid"]:
                render_debt_row_edit(r)
            else:
                render_debt_row(r)
    st.markdown("<div class='section-subheader'>Add New Debt Item</div>", unsafe_allow_html=True)
    new_debt_name = st.text_input("Debt Name (e.g. 'Loft Credit Card')")
    new_debt_balance = st.number_input("Current Balance", min_value=0.0, format="%.2f")
    due_date_opts = ["(None)"] + [f"{d}{'st' if d==1 else 'nd' if d==2 else 'rd' if d==3 else 'th'}" for d in range(1,32)]
    new_due_date = st.selectbox("Due Date (Optional)", due_date_opts, index=0)
    new_min_payment = st.text_input("Minimum Payment (Optional)")
    if st.button("Add Debt"):
        if new_debt_name.strip():
            # Call your add_debt_item function here.
            st.success("New debt item added (functionality assumed).")
            st.experimental_rerun()
    if st.session_state.active_payoff_plan is not None:
        reloaded_debts = load_debt_items()
        match = reloaded_debts[reloaded_debts["rowid"] == st.session_state.active_payoff_plan]
        if not match.empty:
            plan_data = match.iloc[0]
            plan_name = plan_data["debt_name"]
            plan_balance = plan_data["current_balance"]
            plan_due = plan_data["due_date"] if plan_data["due_date"] else ""
            st.markdown("<hr>", unsafe_allow_html=True)
            st.subheader(f"Payoff Plan for {plan_name}")
            st.session_state.temp_payoff_date = st.date_input("What date do you want to pay this off by?",
                                                               value=st.session_state.temp_payoff_date)
            col_d1, col_d2 = st.columns(2)
            if col_d1.button("Submit"):
                insert_monthly_payments_for_debt(plan_name, plan_balance, plan_due, st.session_state.temp_payoff_date)
                st.session_state.active_payoff_plan = None
                clear_query_params()
                st.experimental_rerun()
            if col_d2.button("Cancel"):
                st.session_state.active_payoff_plan = None
                clear_query_params()
                st.experimental_rerun()

# =============================================================================
# Page 3: Budget Overview
# =============================================================================
elif page_choice == "Budget Overview":
    st.markdown("""
    <h1 style='text-align: center; font-size: 50px; font-weight: bold; color: black;
    text-shadow: 0px 0px 10px #00ccff, 0px 0px 20px #00ccff;'>Budget Overview</h1>
    """, unsafe_allow_html=True)
    today = datetime.today()
    first_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_date = first_of_month
    end_date = first_of_month + relativedelta(months=12) - relativedelta(days=1)
    fact_data = load_fact_data()
    fact_data["date"] = pd.to_datetime(fact_data["date"])
    mask = (fact_data["date"] >= start_date) & (fact_data["date"] <= end_date)
    data_12mo = fact_data[mask].copy()
    total_inc = data_12mo[data_12mo["type"]=="income"]["amount"].sum()
    total_exp = data_12mo[data_12mo["type"]=="expense"]["amount"].sum()
    leftover = total_inc - total_exp
    st.markdown(f"""
    <div style='display: flex; justify-content: space-around; text-align:center; padding:10px 0;'>
      <div class='metric-box'>
         <div style='font-size:14px; color:#bbb;'>12-Month Income</div>
         <div style='font-size:20px; font-weight:bold; color:green;'>${total_inc:,.2f}</div>
      </div>
      <div class='metric-box'>
         <div style='font-size:14px; color:#bbb;'>12-Month Expenses</div>
         <div style='font-size:20px; font-weight:bold; color:red;'>${total_exp:,.2f}</div>
      </div>
      <div class='metric-box'>
         <div style='font-size:14px; color:#bbb;'>Leftover</div>
         <div style='font-size:20px; font-weight:bold; color:{"green" if leftover>=0 else "red"};'>${leftover:,.2f}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    # Additional charts or breakdowns can be added here.
