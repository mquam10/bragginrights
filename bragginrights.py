
import streamlit as st
import pandas as pd
import os
import glob
import json
import requests
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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

SALARIES_FOLDER = "salaries"
MANAGERS = ["-", "Mariah", "David", "Amos", "AJ", "Danny"]
SEASON_YEAR = 2025
SHEET_NAME = "BragginRights"

CACHE_FILE = "player_stats_cache.json"

# ----------------------------
# GSheets connection
# ----------------------------
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # Cloud secret
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    # Local JSON fallback
    elif os.path.exists("service_account.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    else:
        raise FileNotFoundError("No Google service account credentials found")
    return gspread.authorize(creds)

gc = get_gspread_client()

# List all spreadsheets the service account can see
for ss in gc.openall():
    print(ss.title)


# ----------------------------
# Load CSV
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

# ----------------------------
# Sheets read/write helpers
# ----------------------------
def load_sheet(worksheet_name):
    sh = gc.open("BragginRights")  # always open the workbook
    worksheet = sh.worksheet(worksheet_name)  # then pick the worksheet
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

def write_sheet(worksheet_name, df):
    sh = gc.open("BragginRights")  # always open the workbook
    worksheet = sh.worksheet(worksheet_name)  # then pick the worksheet
    worksheet.clear()
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())

# ----------------------------
# Lineup save/load
# ----------------------------
def save_lineup(username, lineup, week_key):
    df = load_sheet("leaderboard")
    # Flatten lineup for storing
    new_rows = []
    for slot, player in lineup.items():
        row = {
            "week": week_key,
            "manager": username,
            "slot": slot,
            "player_name": player["name"],
            "position": player["position"],
            "team": player["team"],
            "salary": player["salary"]
        }
        new_rows.append(row)
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True) if not df.empty else pd.DataFrame(new_rows)
    write_sheet("leaderboard", df)

def load_leaderboard_for_week(week_key):
    df = load_sheet("leaderboard")
    return df[df["week"] == week_key] if not df.empty else pd.DataFrame()

# ----------------------------
# Live points from Sleeper
# ----------------------------
def get_player_points(player_id, season, week, cache):
    cache_key = f"{player_id}_{season}_{week}"
    if cache_key in cache:
        return cache[cache_key]
    url = f"https://api.sleeper.app/v1/stats/nfl/player/{player_id}?season={season}&season_type=regular&week={week}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        points = response.json().get("fantasy_points", 0)
    except:
        points = 0
    cache[cache_key] = points
    return points

# ----------------------------
# App UI
# ----------------------------
st.set_page_config(page_title="Family BragginRights DFS", layout="wide")
st.title("🏈 BragginRights DFS League")

username = st.selectbox("Select your manager name", MANAGERS)

latest_csv, current_week_key = load_latest_csv()
if not latest_csv:
    st.error(f"No CSV found in {SALARIES_FOLDER}.")
    st.stop()

df = load_csv(latest_csv)

# Sidebar filters
st.sidebar.subheader("Filter Players")
positions = st.sidebar.multiselect("Positions", df["position"].unique())
teams = st.sidebar.multiselect("Teams", df["team"].unique())
opponents = st.sidebar.multiselect("Opponent", df["opponent"].unique())
salary_range = st.sidebar.slider(
    "Salary Range", int(df["salary"].min()), int(df["salary"].max()), (0, int(df["salary"].max()))
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
# Build Lineup
# ----------------------------
st.subheader("Build Your Lineup")
state_key = f"lineup_{username}_{current_week_key}"

if state_key not in st.session_state:
    st.session_state[state_key] = {}

lineup = st.session_state[state_key]

submitted_df = load_leaderboard_for_week(current_week_key)
submitted_lineup = submitted_df[submitted_df["manager"] == username] if not submitted_df.empty else pd.DataFrame()

if not submitted_lineup.empty:
    st.info("You have already submitted a lineup.")
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

            # Remove already selected
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

    # Display lineup + salary
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
# Weekly Leaderboard with live points
# ----------------------------
st.subheader("🏆 Weekly Leaderboard")

# Load mapping file for Sleeper IDs
MAPPING_FILE = "mappings/fanduel_to_sleeper.json"
if os.path.exists(MAPPING_FILE):
    with open(MAPPING_FILE) as f:
        mapping = json.load(f)
else:
    mapping = {}

player_cache = {}  # clear cache each refresh for live points

submitted_df = load_leaderboard_for_week(current_week_key)
if not submitted_df.empty:
    weekly_display = {}
    for manager in submitted_df["manager"].unique():
        manager_scores = {}
        total_points = 0
        manager_lineup = submitted_df[submitted_df["manager"]==manager]
        for _, row in manager_lineup.iterrows():
            player_name = row["player_name"]
            player_id = mapping.get(player_name)
            points = get_player_points(player_id, SEASON_YEAR, int(current_week_key.split("_week_")[1]), player_cache) if player_id else 0
            manager_scores[row["slot"]] = f"{player_name} ({points} pts)"
            total_points += points
        manager_scores["Total"] = total_points
        weekly_display[manager] = manager_scores
    st.dataframe(pd.DataFrame(weekly_display))

# ----------------------------
# Season Leaderboard
# ----------------------------
st.subheader("📊 Season Leaderboard")
season_df = load_sheet("season")
season_df["Placement Points"] = (
    season_df["weeks_1st"]*10 +
    season_df["weeks_2nd"]*6 +
    season_df["weeks_3rd"]*3
)
season_df = season_df.sort_values(by=["Placement Points", "total_points"], ascending=False)
st.dataframe(season_df)
