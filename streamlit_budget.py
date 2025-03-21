def render_debt_transaction_row(row):
    row_id = row["rowid"]
    name = row["debt_name"]
    balance_str = f"${row['current_balance']:,.2f}"
    due = row["due_date"] if row["due_date"] else "(None)"
    min_pay = row["minimum_payment"] if pd.notnull(row["minimum_payment"]) else "(None)"
    cols = st.columns([4, 1, 1, 1])
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
            try:
                st.experimental_rerun()
            except Exception:
                st.stop()
    with cols[2]:
        # If a payoff plan exists, show a green "Recalc" button; otherwise yellow "Payoff"
        if row.get("payoff_plan_date"):
            st.markdown(f"""<a href="?recalc={row_id}" style="display:inline-block; background-color:green; color:white; font-weight:bold; border-radius:5px; padding:4px 8px; text-decoration:none;">Recalc</a>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""<a href="?payoff={row_id}" style="display:inline-block; background-color:yellow; color:black; font-weight:bold; border-radius:5px; padding:4px 8px; text-decoration:none;">Payoff</a>""", unsafe_allow_html=True)
    with cols[3]:
        if st.button("❌", key=f"delete_debt_{row_id}"):
            remove_debt_item(row_id)
            remove_old_payoff_lines_for_debt(name)
            try:
                st.experimental_rerun()
            except Exception:
                st.stop()
