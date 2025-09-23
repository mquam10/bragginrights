
import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import glob
import json
import requests
import re

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
    "D": 1      # Defense
}

MAPPING_FILE = "mappings/fanduel_to_sleeper.json"
SALARIES_FOLDER = "salaries"
MANAGERS = ["-","Mariah", "David", "Amos", "AJ", "Danny"]

SEASON_YEAR = 2025  # update dynamically if needed
SHEET_NAME = "BragginRights"  # Google Sheet name

# ----------------------------
# Google Sheets Connection
# ----------------------------
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]

    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    elif os.path.exists("service_account.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    else:
        raise FileNotFoundError("No Google service account credentials found")

    return gspread.authorize(creds)

gc = get_gspread_client()

# ----------------------------
# Sheet Helpers
# ----------------------------
def load_sheet(worksheet):
    sh = gc.open(SHEET_NAME)
    ws = sh.worksheet(worksheet)
    data = ws.get_all_records()
    return pd.DataFrame(data)

def write_sheet(worksheet, df):
    sh = gc.open(SHEET_NAME)
    ws = sh.worksheet(worksheet)
    ws.clear()
    if not df.empty:
        ws.update([df.columns.values.tolist()] + df.values.tolist())

# ----------------------------
# Load FanDuel -> Sleeper mapping
# ----------------------------
if os.path.exists(MAPPING_FILE):
    with open(MAPPING_FILE, "r") as f:
        mapping = json.load(f)
else:
    mapping = {}
    st.warning(f"Mapping file not found: {MAPPING_FILE}")

# ----------------------------
# Helpers for CSV + Lineups
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

def save_lineup(username, lineup_dict, week_key):
    try:
        df = load_sheet("Lineups")
    except:
        df = pd.DataFrame(columns=["week", "manager", "slot", "name", "team", "salary", "fppg"])

    # Remove existing lineup for this user/week
    df = df[~((df["week"] == week_key) & (df["manager"] == username))]

    new_rows = []
    for slot, player in lineup_dict.items():
        row = {
            "week": week_key,
            "manager": username,
            "slot": slot,
            "name": player["name"],
            "team": player["team"],
            "salary": player["salary"],
            "fppg": player["fppg"]
        }
        new_rows.append(row)

    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    write_sheet("Lineups", df)

def load_lineup(username, week_key):
    try:
        df = load_sheet("Lineups")
    except:
        return None
    lineup_df = df[(df["week"] == week_key) & (df["manager"] == username)]
    return lineup_df if not lineup_df.empty else None

# ----------------------------
# Sleeper API Live Points
# ----------------------------
def get_player_points(player_id, season, week):
    url = f"https://api.sleeper.app/v1/stats/nfl/player/{player_id}?season={season}&season_type=regular&week={week}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json().get("fantasy_points", 0)
    except:
        return 0

# ----------------------------
# Streamlit App
# ----------------------------
st.set_page_config(page_title="Family BragginRights DFS", layout="wide")
st.title("🏈 BragginRights DFS League")

# Manager selection
username = st.selectbox("Select your manager name", MANAGERS)

# Load latest CSV
latest_csv, current_week_key = load_latest_csv()
if not latest_csv:
    st.error(f"No CSV found in {SALARIES_FOLDER}. Drop the weekly FanDuel CSV there.")
    st.stop()

df = load_csv(latest_csv)
submitted_lineup = load_lineup(username, current_week_key)

# ----------------------------
# Sidebar Filters
# ----------------------------
st.sidebar.subheader("Filter Players")
positions = st.sidebar.multiselect("Positions", df["position"].unique())
teams = st.sidebar.multiselect("Teams", df["team"].unique())
opponents = st.sidebar.multiselect("Opponent", df["opponent"].unique())
salary_range = st.sidebar.slider("Salary Range", int(df["salary"].min()), int(df["salary"].max()), (0, int(df["salary"].max())))

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
# Build Lineup
# ----------------------------
st.subheader("Build Your Lineup")
state_key = f"lineup_{username}_{current_week_key}"

if state_key not in st.session_state:
    st.session_state[state_key] = {}

lineup = st.session_state[state_key]

if submitted_lineup is not None:
    st.info("You have already submitted a lineup. You cannot change it.")
    st.dataframe(submitted_lineup)
else:
    used_players = [p["name"] for p in lineup.values()] if lineup else []
    for pos, count in LINEUP_SLOTS.items():
        for i in range(count):
            label = f"{pos}{'' if count==1 else i+1}"
            pool = df[df["position"].isin(["RB","WR","TE"])] if pos=="FLEX" else df[df["position"]==pos]

            # Apply filters
            if positions:
                pool = pool[pool["position"].isin(positions)]
            if teams:
                pool = pool[pool["team"].isin(teams)]
            if opponents:
                pool = pool[pool["opponent"].isin(opponents)]

            pool = pool[~pool["name"].isin([p for p in used_players if p not in lineup.get(label, {}).get("name", [])])]

            options = ["--"] + [f"{r['name']} | ${r['salary']} | {r['fppg']} FPPG" for _,r in pool.iterrows()]
            prior_choice = lineup.get(label)
            prior_choice_str = f"{prior_choice['name']} | ${prior_choice['salary']} | {prior_choice['fppg']} FPPG" if prior_choice else "--"
            if prior_choice_str not in options:
                options.append(prior_choice_str)

            choice = st.selectbox(
                f"Select {label}",
                options,
                index=options.index(prior_choice_str) if prior_choice_str in options else 0,
                key=f"{label}_{username}_{current_week_key}"
            )

            if choice != "--":
                name = choice.split(" | ")[0]
                player_row = df[df["name"]==name].iloc[0].to_dict()
                lineup[label] = player_row
                if name not in used_players:
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
            save_disabled = total_salary > SALARY_CAP
            if save_disabled:
                st.warning("You cannot save: lineup exceeds the salary cap!")
            if st.button("Save Lineup", disabled=save_disabled):
                save_lineup(username, lineup, current_week_key)
                st.success("Lineup saved! Refresh to view leaderboard.")
        with col2:
            if st.button("Reset Lineup"):
                st.session_state[state_key] = {}
                st.experimental_rerun()

# ----------------------------
# Weekly Leaderboard
# ----------------------------
st.subheader("🏆 Family Weekly Leaderboard")

try:
    lineups_df = load_sheet("Lineups")
except:
    lineups_df = pd.DataFrame(columns=["week","manager","slot","name","team","salary","fppg"])

week_lineups = lineups_df[lineups_df["week"] == current_week_key]

if not week_lineups.empty:
    weekly_display = {}
    week_number = int(current_week_key.split("_week_")[1])

    for manager in week_lineups["manager"].unique():
        manager_df = week_lineups[week_lineups["manager"] == manager]
        manager_scores = {}
        total_points = 0
        for _, row in manager_df.iterrows():
            player_name = row["name"]
            player_id = mapping.get(player_name)
            points = get_player_points(player_id, SEASON_YEAR, week_number) if player_id else 0
            manager_scores[row["slot"]] = f"{player_name} ({points} pts)"
            total_points += points
        manager_scores["Total"] = total_points
        weekly_display[manager] = manager_scores

    st.dataframe(pd.DataFrame(weekly_display))
else:
    st.info("No lineups submitted yet.")
