import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from datetime import datetime, date
import calendar
import uuid
from dateutil.relativedelta import relativedelta

# =============================================================================
# Custom CSS
# =============================================================================
st.markdown("""
<style>
/* The row "bar" for each line item */
.line-item {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  background-color: #333;
  padding: 10px;
  border-radius: 5px;
  margin-bottom: 8px;
  width: 100%;
  white-space: nowrap;
}
.line-item > div {
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
  margin-right: 10px;
}

/* Style for HTML links acting as buttons */
.row-button {
  text-decoration: none;
  background-color: #555;
  color: #fff;
  padding: 5px 10px;
  border-radius: 5px;
  margin-left: 5px;
  font-size: 14px;
}
.row-button.remove {
  background-color: #900;
}

/* Mobile adjustments */
@media only screen and (max-width: 600px) {
  .line-item {
    padding: 5px;
    font-size: 14px;
  }
  .row-button {
    font-size: 12px;
    padding: 4px 8px;
  }
}

/* Calendar container for horizontal scrolling */
.calendar-container {
  overflow-x: auto;
  width: 100%;
}
.calendar-container table {
  width: 100%;
  border-collapse: collapse;
  font-size: 16px;
}
@media only screen and (max-width: 600px) {
  .calendar-container table {
    font-size: 12px;
  }
  .calendar-container th, .calendar-container td {
    padding: 5px;
  }
}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# Query Parameter Helpers
# =============================================================================
def get_query_params_fallback():
    if hasattr(st, "query_params"):
        return st.query_params
    else:
        return st.experimental_get_query_params()

def clear_query_params():
    if hasattr(st, "set_query_params"):
        st.set_query_params()
    else:
        st.experimental_set_query_params()

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
        job = client.load_table_from_dataframe(df, table_id,
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"))
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
    job = client.load_table_from_dataframe(df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"))
    job.result()

# =============================================================================
# Custom Row Rendering Functions for Budget Planning
# =============================================================================
def render_budget_row_html(row, color_class):
    """Render a budget row (non-edit mode) as a custom HTML bar with inline buttons."""
    row_id = row["rowid"]
    date_str = row["date"].strftime("%Y-%m-%d")
    item_str = row["budget_item"]
    amount_str = f"${row['amount']:,.2f}"
    html = f"""
    <div class="line-item">
      <div style="min-width: 100px; font-weight:bold; color:#fff;">{date_str}</div>
      <div style="flex:1; margin-left:15px; color:#fff;">{item_str}</div>
      <div style="min-width:80px; margin-left:15px; color:{color_class};">{amount_str}</div>
      <div>
         <a class="row-button" href="?action=edit&rowid={row_id}" target="_self" onclick="window.location.href=this.href; return false;">Edit</a>
      </div>
      <div>
         <a class="row-button remove" href="?action=remove&rowid={row_id}" target="_self" onclick="window.location.href=this.href; return false;">❌</a>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

def render_budget_row_edit(row, color_class):
    """Render the editing interface for a budget row using native Streamlit inputs."""
    row_id = row["rowid"]
    item_str = row["budget_item"]
    amount_str = f"${row['amount']:,.2f}"
    st.markdown(f"""
    <div class="line-item">
      <div style="min-width: 100px; font-weight:bold; color:#fff;">Editing...</div>
      <div style="flex:1; margin-left:15px; color:#fff;">{item_str}</div>
      <div style="min-width:80px; margin-left:15px; color:{color_class};">{amount_str}</div>
    </div>
    """, unsafe_allow_html=True)
    st.session_state.temp_budget_edit_date = st.date_input("Date", value=row["date"], key=f"edit_date_{row_id}")
    st.session_state.temp_budget_edit_amount = st.number_input("Amount", min_value=0.0, format="%.2f",
                                                               value=float(row["amount"]), key=f"edit_amount_{row_id}")
    col1, col2 = st.columns(2)
    if col1.button("Save", key=f"save_{row_id}"):
        update_fact_row(row_id, st.session_state.temp_budget_edit_date,
                        st.session_state.temp_budget_edit_amount)
        st.session_state.editing_budget_item = None
        clear_query_params()
        st.rerun()
    if col2.button("Cancel", key=f"cancel_{row_id}"):
        st.session_state.editing_budget_item = None
        clear_query_params()
        st.rerun()

# =============================================================================
# Custom Row Rendering Functions for Debt Domination
# =============================================================================
def render_debt_row_html(row):
    """Render a debt row (non-edit mode) as a custom HTML bar with inline buttons."""
    row_id = row["rowid"]
    row_name = row["debt_name"]
    row_balance = row["current_balance"]
    row_due = row["due_date"] if row["due_date"] else "(None)"
    row_min = row["minimum_payment"] if pd.notnull(row["minimum_payment"]) else "(None)"
    payoff_text = "Recalc" if row.get("payoff_plan_date") else "Payoff"
    html = f"""
    <div class="line-item">
      <div style="min-width: 60px; font-weight:bold; color:#fff;">{row_name}</div>
      <div style="flex:1; margin-left:15px; color:#fff;">Due: {row_due}, Min: {row_min}</div>
      <div style="min-width:80px; margin-left:15px; color:red;">${row_balance:,.2f}</div>
      <div>
         <a class="row-button" href="?action=edit_debt&rowid={row_id}" target="_self" onclick="window.location.href=this.href; return false;">Edit</a>
      </div>
      <div>
         <a class="row-button" href="?action=payoff&rowid={row_id}" target="_self" onclick="window.location.href=this.href; return false;">{payoff_text}</a>
      </div>
      <div>
         <a class="row-button remove" href="?action=remove_debt&rowid={row_id}" target="_self" onclick="window.location.href=this.href; return false;">❌</a>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

def render_debt_row_edit(row):
    """Render the editing interface for a debt row using native Streamlit inputs."""
    row_id = row["rowid"]
    row_name = row["debt_name"]
    row_balance = row["current_balance"]
    row_due = row["due_date"] if row["due_date"] else "(None)"
    row_min = row["minimum_payment"] if pd.notnull(row["minimum_payment"]) else "(None)"
    st.markdown(f"""
    <div class="line-item">
      <div style="min-width: 60px; font-weight:bold; color:#fff;">Editing: {row_name}</div>
      <div style="flex:1; margin-left:15px; color:#fff;">Due: {row_due}, Min: {row_min}</div>
      <div style="min-width:80px; margin-left:15px; color:red;">${row_balance:,.2f}</div>
    </div>
    """, unsafe_allow_html=True)
    st.session_state.temp_new_balance = st.number_input("New Balance", min_value=0.0, format="%.2f",
                                                         value=float(row_balance), key=f"edit_debt_balance_{row_id}")
    col1, col2 = st.columns(2)
    if col1.button("Save", key=f"save_debt_{row_id}"):
        update_debt_item(row_id, st.session_state.temp_new_balance)
        st.session_state.editing_debt_item = None
        clear_query_params()
        st.rerun()
    if col2.button("Cancel", key=f"cancel_debt_{row_id}"):
        st.session_state.editing_debt_item = None
        clear_query_params()
        st.rerun()

# =============================================================================
# Process Query Parameters for Actions
# =============================================================================
params = get_query_params_fallback()
if "action" in params and "rowid" in params:
    action = params["action"][0]
    rowid = params["rowid"][0]
    if action == "edit":
        st.session_state.editing_budget_item = rowid
        clear_query_params()
        st.experimental_rerun()
    elif action == "remove":
        remove_fact_row(rowid)
        clear_query_params()
        st.experimental_rerun()
    elif action == "edit_debt":
        st.session_state.editing_debt_item = rowid
        clear_query_params()
        st.experimental_rerun()
    elif action == "remove_debt":
        remove_debt_item(rowid)
        clear_query_params()
        st.experimental_rerun()
    elif action == "payoff":
        st.session_state.active_payoff_plan = rowid
        clear_query_params()
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
                   text-shadow: 0px 0px 10px #00ccff, 0px 0px 20px #00ccff;'>
            Mielke Budget
        </h1>
    """, unsafe_allow_html=True)
    
    # Month navigation
    nav_col1, nav_col2, nav_col3, nav_col4 = st.columns([0.25, 1, 2, 1])
    with nav_col2:
        if st.button("Previous Month"):
            if st.session_state.current_month == 1:
                st.session_state.current_month = 12
                st.session_state.current_year -= 1
            else:
                st.session_state.current_month -= 1
            st.rerun()
    with nav_col3:
        st.markdown(f"""
        <div style='text-align: center; font-size: 24px; font-weight: bold; padding: 10px;'>
            {calendar.month_name[st.session_state.current_month]} {st.session_state.current_year}
        </div>
        """, unsafe_allow_html=True)
    with nav_col4:
        if st.button("Next Month"):
            if st.session_state.current_month == 12:
                st.session_state.current_month = 1
                st.session_state.current_year += 1
            else:
                st.session_state.current_month += 1
            st.rerun()
    
    # Load fact data and filter by current month/year
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
        <div style='background-color:#333; padding:10px 15px; border-radius:10px;'>
            <div style='font-size:14px; color:#bbb;'>Total Income</div>
            <div style='font-size:20px; font-weight:bold; color:green;'>${total_income:,.2f}</div>
        </div>
        <div style='background-color:#333; padding:10px 15px; border-radius:10px;'>
            <div style='font-size:14px; color:#bbb;'>Total Expenses</div>
            <div style='font-size:20px; font-weight:bold; color:red;'>${total_expenses:,.2f}</div>
        </div>
        <div style='background-color:#333; padding:10px 15px; border-radius:10px;'>
            <div style='font-size:14px; color:#bbb;'>Leftover</div>
            <div style='font-size:20px; font-weight:bold; color:{"green" if leftover>=0 else "red"};'>${leftover:,.2f}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Calendar display
    days_in_month = calendar.monthrange(st.session_state.current_year, st.session_state.current_month)[1]
    first_weekday = (calendar.monthrange(st.session_state.current_year, st.session_state.current_month)[0] + 1) % 7
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
                cell_html += f"<br><span style='color:{color};'>${row['amount']:,.2f} ({row['budget_item']})</span>"
            calendar_grid[week][weekday] = cell_html
            day_counter += 1
    cal_df = pd.DataFrame(calendar_grid, columns=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"])
    calendar_html = cal_df.to_html(index=False, escape=False)
    st.markdown(f'<div class="calendar-container">{calendar_html}</div>', unsafe_allow_html=True)
    
    # =============================================================================
    # Add New Income/Expense Form with Drop-Downs for Category & Budget Item
    # =============================================================================
    st.markdown("<div class='section-subheader'>Add New Income/Expense</div>", unsafe_allow_html=True)
    date_input = st.date_input("Date", value=datetime.today(), label_visibility="collapsed")
    type_input = st.selectbox("Type", ["income", "expense"], label_visibility="collapsed")
    
    # Load dimension data for selected type
    dimension_df = load_dimension_rows(type_input)
    all_categories = sorted(dimension_df["category"].unique())
    if not all_categories:
        all_categories = ["(No categories yet)"]
    selected_category = st.selectbox("Category", all_categories, key="cat_dropdown")
    if st.button("➕ Add New Category", key="add_category"):
        st.session_state.show_new_category_form = True
    if st.session_state.show_new_category_form:
        new_cat = st.text_input("New Category", key="new_cat_input")
        col_cat1, col_cat2 = st.columns(2)
        if col_cat1.button("Save Category", key="save_category"):
            if new_cat.strip():
                add_dimension_row(type_input, new_cat.strip(), "")
            st.session_state.show_new_category_form = False
            st.experimental_rerun()
        if col_cat2.button("Cancel", key="cancel_category"):
            st.session_state.show_new_category_form = False
    
    items_for_cat = dimension_df[dimension_df["category"] == selected_category]["budget_item"].unique()
    items_for_cat = [i for i in items_for_cat if i != ""]
    if not items_for_cat:
        items_for_cat = ["(No items yet)"]
    selected_budget_item = st.selectbox("Budget Item", items_for_cat, key="budget_item_dropdown")
    if st.button("➕ Add New Budget Item", key="add_budget_item"):
        st.session_state.show_new_item_form = True
    if st.session_state.show_new_item_form:
        new_item = st.text_input("New Budget Item", key="new_item_input")
        col_item1, col_item2 = st.columns(2)
        if col_item1.button("Save Budget Item", key="save_item"):
            if new_item.strip():
                add_dimension_row(type_input, selected_category, new_item.strip())
            st.session_state.show_new_item_form = False
            st.experimental_rerun()
        if col_item2.button("Cancel", key="cancel_item"):
            st.session_state.show_new_item_form = False
    
    amount_input = st.number_input("Amount", min_value=0.0, format="%.2f", label_visibility="collapsed")
    note_input = st.text_area("Note", label_visibility="collapsed")
    if st.button("Add Transaction"):
        new_row_id = str(uuid.uuid4())
        new_tx = pd.DataFrame([{
            "rowid": new_row_id,
            "date": date_input,
            "type": type_input,
            "amount": amount_input,
            "category": selected_category,
            "budget_item": selected_budget_item,
            "credit_card": None,
            "note": note_input
        }])
        save_fact_data(new_tx)
        st.rerun()
    
    st.markdown("<div class='section-subheader'>Transactions This Month</div>", unsafe_allow_html=True)
    if filtered_data.empty:
        st.write("No transactions found for this month.")
    else:
        for _, row in filtered_data.iterrows():
            if st.session_state.editing_budget_item == row["rowid"]:
                render_budget_row_edit(row, "#00cc00" if row["type"]=="income" else "#ff4444")
            else:
                render_budget_row_html(row, "#00cc00" if row["type"]=="income" else "#ff4444")

# =============================================================================
# Page 2: Debt Domination
# =============================================================================
elif page_choice == "Debt Domination":
    st.markdown("""
        <h1 style='text-align: center; font-size: 50px; font-weight: bold; color: black;
                   text-shadow: 0px 0px 10px #00ccff, 0px 0px 20px #00ccff;'>
            Debt Domination
        </h1>
    """, unsafe_allow_html=True)
    debt_df = load_debt_items()
    if debt_df.empty:
        st.write("No debt items found.")
    else:
        for _, row in debt_df.iterrows():
            if st.session_state.editing_debt_item == row["rowid"]:
                render_debt_row_edit(row)
            else:
                render_debt_row_html(row)
    
    st.markdown("<div class='section-subheader'>Add New Debt Item</div>", unsafe_allow_html=True)
    new_debt_name = st.text_input("Debt Name (e.g. 'Loft Credit Card')")
    new_debt_balance = st.number_input("Current Balance", min_value=0.0, format="%.2f")
    due_date_options = ["(None)"] + [f"{d}{'st' if d==1 else 'nd' if d==2 else 'rd' if d==3 else 'th'}" for d in range(1,32)]
    new_due_date = st.selectbox("Due Date (Optional)", due_date_options, index=0)
    new_min_payment = st.text_input("Minimum Payment (Optional)")
    if st.button("Add Debt"):
        if new_debt_name.strip():
            # Here you would call your add_debt_item function.
            st.success("New debt item added (functionality assumed).")
            st.rerun()
    
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
            col_debt1, col_debt2 = st.columns(2)
            if col_debt1.button("Submit"):
                insert_monthly_payments_for_debt(plan_name, plan_balance, plan_due, st.session_state.temp_payoff_date)
                st.session_state.active_payoff_plan = None
                clear_query_params()
                st.rerun()
            if col_debt2.button("Cancel"):
                st.session_state.active_payoff_plan = None
                clear_query_params()
                st.rerun()

# =============================================================================
# Page 3: Budget Overview
# =============================================================================
elif page_choice == "Budget Overview":
    st.markdown("""
        <h1 style='text-align: center; font-size: 50px; font-weight: bold; color: black;
                   text-shadow: 0px 0px 10px #00ccff, 0px 0px 20px #00ccff;'>
            Budget Overview
        </h1>
    """, unsafe_allow_html=True)
    today = datetime.today()
    first_of_this_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_date = first_of_this_month
    end_date = first_of_this_month + relativedelta(months=12) - relativedelta(days=1)
    fact_data = load_fact_data()
    fact_data["date"] = pd.to_datetime(fact_data["date"])
    mask = (fact_data["date"] >= start_date) & (fact_data["date"] <= end_date)
    data_12mo = fact_data[mask].copy()
    total_inc = data_12mo[data_12mo["type"]=="income"]["amount"].sum()
    total_exp = data_12mo[data_12mo["type"]=="expense"]["amount"].sum()
    leftover = total_inc - total_exp
    st.markdown(f"""
    <div style='display:flex; justify-content:space-around; text-align:center; padding:10px 0;'>
        <div style='background-color:#333; padding:10px 15px; border-radius:10px;'>
            <div style='font-size:14px; color:#bbb;'>12-Month Income</div>
            <div style='font-size:20px; font-weight:bold; color:green;'>${total_inc:,.2f}</div>
        </div>
        <div style='background-color:#333; padding:10px 15px; border-radius:10px;'>
            <div style='font-size:14px; color:#bbb;'>12-Month Expenses</div>
            <div style='font-size:20px; font-weight:bold; color:red;'>${total_exp:,.2f}</div>
        </div>
        <div style='background-color:#333; padding:10px 15px; border-radius:10px;'>
            <div style='font-size:14px; color:#bbb;'>Leftover</div>
            <div style='font-size:20px; font-weight:bold; color:{"green" if leftover>=0 else "red"};'>${leftover:,.2f}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    # Additional charts or breakdowns can be added here.
