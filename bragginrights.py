
import streamlit as st
import pandas as pd
import os
import glob
import json
import requests
import re
import gspread
from google.oauth2.service_account import Credentials

# ----------------------------
# Config
# ----------------------------
SALARY_CAP = 60000
LINEUP_SLOTS = {
    "QB": 1,
    "RB": 2,
    "WR": 3,
    "TE": 1,
    "FLEX": 1,  # RB/WR/TE
    "D": 1
}

MANAGERS = ["-","Mariah", "David", "Amos", "AJ", "Danny"]
SEASON_YEAR = 2025  # update dynamically if needed

SALARIES_FOLDER = "salaries"
MAPPING_FILE = "mappings/fanduel_to_sleeper.json"

# ----------------------------
# Setup Google Sheets
# ----------------------------
# Authorize gspread using service account stored in Streamlit secrets
creds_dict = st.secrets["gcp_service_account"]
creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
)
gc = gspread.authorize(creds)

# Open workbook and sheets
WORKBOOK_NAME = "BragginRights"
sh = gc.open(WORKBOOK_NAME)
leaderboard_ws = sh.worksheet("leaderboard")
season_ws = sh.worksheet("season")

# ----------------------------
# Load FanDuel -> Sleeper mapping
# ----------------------------
if os.path.exists(MAPPING_FILE):
    with open(MAPPING_FILE, "r") as f:
        mapping = json.load(f)
else:
    st.error(f"Mapping file not found: {MAPPING_FILE}")
    st.stop()

# ----------------------------
# Helper functions
# ----------------------------
def load_latest_csv():
    csv_files = sorted(glob.glob(os.path.join(SALARIES_FOLDER, "*.csv")))
    if csv_files:
        latest = csv_files[-1]
        match = re.search(r'(\d{4})_week_(\d+)', latest)
        if match:
            year, week = match.groups()
            return latest, f"{year}_week_{week}"
    return None, "unknown_week"

def load_csv(file):
    df = pd.read_csv(file)
    df.columns = [c.strip().lower() for c in df.columns]
    df["name"] = df["first name"] + " " + df["last name"]
    df = df[["name", "position", "team", "opponent", "salary", "fppg"]]
    df["position"] = df["position"].replace({"DEF": "D"})
    df["fppg"] = df["fppg"].round(2)
    return df

def get_player_points(player_id, season, week):
    """Fetch points from Sleeper API live"""
    url = f"https://api.sleeper.app/v1/stats/nfl/player/{player_id}?season={season}&season_type=regular&week={week}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json().get("fantasy_points", 0)
    except:
        return 0

# ----------------------------
# Google Sheets helpers
# ----------------------------
def load_sheet(ws):
    """Load sheet as DataFrame"""
    data = ws.get_all_records()
    return pd.DataFrame(data)

def write_sheet(ws, df):
    """Overwrite entire sheet"""
    ws.clear()
    ws.update([df.columns.values.tolist()] + df.values.tolist())

# ----------------------------
# Streamlit UI
# ----------------------------
st.set_page_config(page_title="Family BragginRights DFS", layout="wide")
st.title("🏈 BragginRights DFS League")

username = st.selectbox("Select your manager name", MANAGERS)

latest_csv, current_week_key = load_latest_csv()
if not latest_csv:
    st.error(f"No CSV found in {SALARIES_FOLDER}. Drop the weekly FanDuel CSV there.")
    st.stop()

df = load_csv(latest_csv)

# Load weekly leaderboard
leaderboard_df = load_sheet(leaderboard_ws)
submitted_lineup = leaderboard_df[leaderboard_df['week']==current_week_key].set_index('manager').to_dict('index').get(username)

# ----------------------------
# Sidebar Filters
# ----------------------------
st.sidebar.subheader("Filter Players")
positions = st.sidebar.multiselect("Positions", df["position"].unique())
teams = st.sidebar.multiselect("Teams", df["team"].unique())
opponents = st.sidebar.multiselect("Opponent", df["opponent"].unique())
salary_range = st.sidebar.slider(
    "Salary Range",
    int(df["salary"].min()), int(df["salary"].max()),
    (0, int(df["salary"].max()))
)

filtered_df = df.copy()
if positions:
    filtered_df = filtered_df[filtered_df["position"].isin(positions)]
if teams:
    filtered_df = filtered_df[filtered_df["team"].isin(teams)]
if opponents:
    filtered_df = filtered_df[filtered_df["opponent"].isin(opponents)]
filtered_df = filtered_df[(filtered_df["salary"] >= salary_range[0]) & (filtered_df["salary"] <= salary_range[1])]
st.subheader(f"Available Players — {current_week_key}")
st.dataframe(filtered_df)

# ----------------------------
# Build lineup
# ----------------------------
st.subheader("Build Your Lineup")
if "lineup" not in st.session_state:
    st.session_state["lineup"] = {}

lineup = st.session_state["lineup"]

if submitted_lineup:
    st.info("You have already submitted a lineup. You cannot change it.")
    st.dataframe(pd.DataFrame([submitted_lineup]))
else:
    used_players = []
    for pos, count in LINEUP_SLOTS.items():
        for i in range(count):
            label = f"{pos}{'' if count==1 else i+1}"
            pool = df[df["position"].isin(["RB","WR","TE"])] if pos=="FLEX" else df[df["position"]==pos]
            if positions:
                pool = pool[pool["position"].isin(positions)]
            if teams:
                pool = pool[pool["team"].isin(teams)]
            if opponents:
                pool = pool[pool["opponent"].isin(opponents)]
            pool = pool[~pool["name"].isin(used_players)]
            options = ["--"] + [f"{r['name']} | ${r['salary']} | {r['fppg']} FPPG" for _, r in pool.iterrows()]
            choice = st.selectbox(f"Select {label}", options, key=f"{label}_{username}")
            if choice != "--":
                name = choice.split(" | ")[0]
                player_row = df[df["name"]==name].iloc[0].to_dict()
                lineup[label] = player_row
                used_players.append(name)
            elif label in lineup:
                del lineup[label]

    if lineup:
        lineup_df = pd.DataFrame.from_dict(lineup, orient="index")
        total_salary = lineup_df["salary"].sum()
        remaining = SALARY_CAP - total_salary
        st.subheader("Your Lineup")
        st.dataframe(lineup_df)
        st.markdown(f"**Total Salary:** ${total_salary:,}")
        st.markdown(f"**Remaining Salary:** ${remaining:,}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Save Lineup"):
                df_row = {"manager": username, "week": current_week_key}
                df_row.update({k: v["name"] for k, v in lineup.items()})
                leaderboard_df = pd.concat([leaderboard_df, pd.DataFrame([df_row])], ignore_index=True)
                write_sheet(leaderboard_ws, leaderboard_df)
                st.success("Lineup saved! Refresh to view leaderboard.")
        with col2:
            if st.button("Reset Lineup"):
                st.session_state["lineup"] = {}
                st.experimental_rerun()

# ----------------------------
# Weekly leaderboard with live points
# ----------------------------
st.subheader("🏆 Weekly Leaderboard")
week_number = int(current_week_key.split("_week_")[1])
weekly_display = []

for idx, row in leaderboard_df[leaderboard_df['week']==current_week_key].iterrows():
    total_points = 0
    row_display = {"Manager": row['manager']}
    for slot in LINEUP_SLOTS:
        player_name = row.get(slot, "")
        player_id = mapping.get(player_name)
        points = get_player_points(player_id, SEASON_YEAR, week_number) if player_id else 0
        row_display[slot] = f"{player_name} ({points} FPPG)" if player_name else ""
        total_points += points
    row_display["Total"] = total_points
    weekly_display.append(row_display)

st.dataframe(pd.DataFrame(weekly_display).sort_values(by="Total", ascending=False))

# ----------------------------
# Season leaderboard
# ----------------------------
st.subheader("📊 Season Leaderboard")
season_df = load_sheet(season_ws)
# Add missing managers if needed
for m in MANAGERS:
    if m == "-":
        continue
    if m not in season_df['Manager'].values:
        season_df = pd.concat([season_df, pd.DataFrame([{"Manager": m, "weeks_1st": 0, "weeks_2nd": 0, "weeks_3rd": 0, "total_points": 0}])], ignore_index=True)

season_df["Placement Points"] = season_df["weeks_1st"]*10 + season_df["weeks_2nd"]*6 + season_df["weeks_3rd"]*3
season_df = season_df.sort_values(by="Placement Points", ascending=False)
st.dataframe(season_df)

# Save season sheet
write_sheet(season_ws, season_df)
