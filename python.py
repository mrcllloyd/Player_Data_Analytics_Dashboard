# ⚙️ Imports
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from fpdf import FPDF
from rapidfuzz import fuzz
import tempfile

# 🧮 Load and Merge Data
@st.cache_data
def load_data():
    player_info = pd.read_csv("player_info.csv")
    usage = pd.read_csv("sp1_dw_aggr.csv")

    usage['playerid'] = usage['playerid'].astype(str)
    usage['reportdate'] = pd.to_datetime(usage['date_time'])
    usage['wageramount'] = usage['total_bet']
    usage['holdamount'] = usage['total_bet'] - usage['total_win']
    usage['wagernum'] = usage['txn_count']

    player_info['player_id'] = player_info['player_id'].astype(str)
    merged = usage.merge(player_info, left_on='playerid', right_on='player_id', how='left')
    merged['occupation'] = merged['nature_of_work']

    def classify_risk(row):
        if row['wageramount'] < 5000:
            return "Green (Normal)"
        elif row['wageramount'] < 25000:
            return "Amber (At Risk)"
        elif row['wageramount'] < 100000:
            return "Red (Pathological)"
        else:
            return "STOP (Exclude)"
    merged['risk_level'] = merged.apply(classify_risk, axis=1)
    return merged, player_info

merged_df, player_info = load_data()

# 🎛️ Sidebar Filters
st.sidebar.title("Filters")
date_range = st.sidebar.date_input("Date Range", [merged_df['reportdate'].min(), merged_df['reportdate'].max()])
sp_options = ['All'] + sorted(merged_df['SP_NAME'].dropna().unique().tolist())
selected_sp = st.sidebar.selectbox("Select SP_NAME", sp_options)

start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
filtered = merged_df[(merged_df['reportdate'] >= start_date) & (merged_df['reportdate'] <= end_date)]
if selected_sp != 'All':
    filtered = filtered[filtered['SP_NAME'] == selected_sp]

# 🧭 Granularity
days_range = (end_date - start_date).days
if days_range <= 7:
    granularity = 'Daily'
    filtered['period'] = filtered['reportdate'].dt.date
elif days_range <= 60:
    granularity = 'Weekly'
    filtered['period'] = filtered['reportdate'].dt.to_period("W").dt.start_time
elif days_range <= 365:
    granularity = 'Monthly'
    filtered['period'] = filtered['reportdate'].dt.to_period("M").dt.start_time
else:
    granularity = 'Yearly'
    filtered['period'] = filtered['reportdate'].dt.to_period("Y").dt.start_time

st.title(" Player Risk Dashboard")
st.write(f"📅 Date Range: {start_date.date()} to {end_date.date()} | SP_NAME: {selected_sp} | Granularity: {granularity}")

# 📈 Wager Summary
summary = filtered.groupby('period').agg(
    total_players=('playerid', 'nunique'),
    total_wager=('wageramount', 'sum'),
    total_hold=('holdamount', 'sum')
).reset_index()
st.subheader(f"📈 Wager Trend Over Time for {selected_sp}")
st.line_chart(summary.set_index('period')['total_wager'])

# 🚩 Risk Flags
player_metrics = filtered.groupby(['playerid', 'occupation']).agg(
    total_sessions=('wagernum', 'sum'),
    total_wager=('wageramount', 'sum'),
    avg_bet=('wageramount', 'mean'),
    max_single_bet=('wageramount', 'max'),
    wager_days=('reportdate', 'nunique')
).reset_index()

player_metrics['avg_wager_per_day'] = player_metrics['total_wager'] / player_metrics['wager_days']
player_metrics['big_bet_flag'] = player_metrics['max_single_bet'] >= 100000
player_metrics['high_freq_flag'] = player_metrics['total_sessions'] >= 50
player_metrics['daily_spike_flag'] = player_metrics['avg_wager_per_day'] >= 20000

flag_summary = player_metrics.groupby('occupation')[['big_bet_flag', 'high_freq_flag', 'daily_spike_flag']].sum()
st.subheader("🚩 Risk Flags by Occupation")
if not flag_summary.empty:
    st.bar_chart(flag_summary)
else:
    st.info("No risk flags detected.")

# 📊 Risk Levels
risk_summary = filtered.groupby('risk_level').agg(
    unique_players=('playerid', 'nunique'),
    total_wager=('wageramount', 'sum'),
    total_hold=('holdamount', 'sum')
).reset_index()
st.subheader("📊 Risk Level Distribution")
st.dataframe(risk_summary)
st.bar_chart(filtered['risk_level'].value_counts())

# 🏅 Top Players
st.subheader(f" Top 10 Players by Wager for {selected_sp}")
top_players = filtered.sort_values(by='wageramount', ascending=False).head(10)[[
    'playerid', 'gamename', 'wageramount', 'holdamount', 'risk_level', 'occupation'
]]
st.dataframe(top_players)

# 🔐 KYC Analysis
st.subheader("📌 KYC Status Analysis")
player_info['registered_date'] = pd.to_datetime(player_info['registered_date'], errors='coerce')
player_info['verify_date'] = pd.to_datetime(player_info['verify_date'], errors='coerce')
player_info['ts'] = pd.to_datetime(player_info['ts'], errors='coerce')

verified_players = player_info[
    (player_info['kyc_status'].str.lower() == 'verified') & (player_info['verify_date'].notna())
]
today = player_info['ts'].max()
unverified_players = player_info[
    (player_info['kyc_status'].str.lower() != 'verified') &
    ((today - player_info['registered_date']) >= pd.Timedelta(days=3))
]
kyc_summary = pd.DataFrame({
    "Status": ["Verified", "Unverified (3+ days)"],
    "Player Count": [len(verified_players), len(unverified_players)]
})
conversion_rate = len(verified_players) / len(player_info) * 100 if len(player_info) > 0 else 0
st.metric("✅ KYC Conversion Rate", f"{conversion_rate:.2f}%")

if not verified_players.empty:
    kyc_timeline = verified_players.copy()
    kyc_timeline['verify_date'] = pd.to_datetime(kyc_timeline['verify_date'], errors='coerce')
    timeline_summary = (
        kyc_timeline.groupby(kyc_timeline['verify_date'].dt.to_period("M"))
        .size().reset_index(name='verified_count')
    )
    timeline_summary['verify_date'] = timeline_summary['verify_date'].dt.to_timestamp()
    if not timeline_summary.empty:
        st.subheader("📆 Verified Players Over Time")
        st.line_chart(timeline_summary.set_index('verify_date')['verified_count'])

player_info['kyc_days'] = (player_info['verify_date'] - player_info['registered_date']).dt.days
valid_durations = player_info[player_info['kyc_days'].notnull() & (player_info['kyc_days'] >= 0)]
if not valid_durations.empty:
    avg_days = valid_durations['kyc_days'].mean()
    st.metric("⏱️ Avg Days to Verify", f"{avg_days:.1f} days")
    fig_dur, ax_dur = plt.subplots()
    sns.histplot(valid_durations['kyc_days'], bins=20, ax=ax_dur, color='skyblue')
    ax_dur.set_title("Distribution of Days to KYC Completion")
    st.pyplot(fig_dur)

fig_kyc, ax = plt.subplots()
ax.bar(kyc_summary['Status'], kyc_summary['Player Count'], color=['green', 'red'])
ax.set_title("KYC Verification Summary")
st.pyplot(fig_kyc)

# 🧠 Fuzzy Matching
st.subheader("🧠 Fuzzy Matching: Possible Duplicate Accounts")
expected_columns = ['first_name', 'last_name', 'email_address', 'username', 'contact_information']
identity_columns = [col for col in expected_columns if col in player_info.columns]

if len(identity_columns) < 2:
    st.warning("Not enough identity columns for fuzzy matching.")
    fuzzy_df = pd.DataFrame()
else:
    cleaned_info = player_info.dropna(subset=identity_columns).copy()
    cleaned_info['identity_string'] = cleaned_info[identity_columns].astype(str).apply(
        lambda row: ' '.join(row.str.lower().str.strip()), axis=1)
    subset = cleaned_info[['player_id', 'identity_string']].head(300)
    fuzzy_results = []
    for i in range(len(subset)):
        for j in range(i + 1, len(subset)):
            score = fuzz.token_sort_ratio(subset.iloc[i]['identity_string'], subset.iloc[j]['identity_string'])
            if score >= 90:
                fuzzy_results.append({
                    'player1': subset.iloc[i]['player_id'],
                    'player2': subset.iloc[j]['player_id'],
                    'similarity_score': score
                })
    fuzzy_df = pd.DataFrame(fuzzy_results)

if not fuzzy_df.empty:
    st.dataframe(fuzzy_df.sort_values(by='similarity_score', ascending=False).head(20))
else:
    st.info("No highly similar player profiles detected.")

# 📄 PDF Export
st.markdown("---")
if st.button("📄 Download Full Dashboard as PDF"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Player Risk Dashboard Summary", ln=True)
    pdf.cell(0, 10, f"Date Range: {start_date.date()} to {end_date.date()} | SP_NAME: {selected_sp}", ln=True)

    if 'fig_kyc' in locals():
        kyc_chart = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        fig_kyc.savefig(kyc_chart.name, dpi=300, bbox_inches='tight')
        pdf.add_page()
        pdf.image(kyc_chart.name, x=10, y=30, w=190)

    if 'fig_dur' in locals():
        dur_chart = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        fig_dur.savefig(dur_chart.name, dpi=300, bbox_inches='tight')
        pdf.add_page()
        pdf.image(dur_chart.name, x=10, y=30, w=190)

    if not fuzzy_df.empty:
        pdf.add_page()
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Top 10 Fuzzy Matched Players", ln=True)
        pdf.set_font("Arial", '', 10)
        for _, row in fuzzy_df.sort_values(by='similarity_score', ascending=False).head(10).iterrows():
            txt = f"{row['player1']} ↔ {row['player2']} | Score: {row['similarity_score']}"
            pdf.cell(0, 8, txt.encode('latin-1', 'replace').decode('latin-1'), ln=True)

    pdf_path = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf").name
    pdf.output(pdf_path)
    with open(pdf_path, "rb") as f:
        st.download_button("Download PDF", f.read(), file_name="dashboard_summary.pdf", mime="application/pdf")
