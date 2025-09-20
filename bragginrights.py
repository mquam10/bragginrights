# bragginrights.py
import streamlit as st
import pandas as pd
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

LEADERBOARD_FILE = "leaderboard.json"
SEASON_FILE = "season_leaderboard.json"
MAPPING_FILE = "mappings/fanduel_to_sleeper.json"
SALARIES_FOLDER = "salaries"
MANAGERS = ["-","Mariah", "David", "Amos", "AJ", "Danny"]

CACHE_FILE = "player_stats_cache.json"
SEASON_YEAR = 2025  # update dynamically if needed

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
# Helper Functions
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
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, "r") as f:
            leaderboard = json.load(f)
    else:
        leaderboard = {}
    if week_key not in leaderboard:
        leaderboard[week_key] = {}
    leaderboard[week_key][username] = lineup_dict
    with open(LEADERBOARD_FILE, "w") as f:
        json.dump(leaderboard, f, indent=2)

def load_leaderboard():
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, "r") as f:
            return json.load(f)
    return {}

def load_season():
    if os.path.exists(SEASON_FILE):
        with open(SEASON_FILE, "r") as f:
            return json.load(f)
    else:
        return {manager: {"total_points": 0, "weeks_1st": 0, "weeks_2nd": 0, "weeks_3rd": 0} 
                for manager in MANAGERS}

# ----------------------------
# Streamlit App
# ----------------------------
st.set_page_config(page_title="Family BragginRights DFS", layout="wide")
st.title("🏈 BragginRights DFS League")

# Manager selection
username = st.selectbox("Select your manager name", MANAGERS)

# ----------------------------
# Admin CSV Upload
# ----------------------------
if username in ["Mariah"]:  # admins only
    st.sidebar.subheader("Admin: Upload Weekly CSV")
    uploaded_file = st.sidebar.file_uploader(
        "Upload weekly FanDuel CSV (e.g., 2025_week_3.csv)", 
        type="csv"
    )
    if uploaded_file:
        save_path = os.path.join(SALARIES_FOLDER, uploaded_file.name)
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.sidebar.success(f"Saved {uploaded_file.name}!")


# ----------------------------
# Admin CSV / JSON Upload (only for Mariah)
# ----------------------------
if username == "Mariah":
    st.sidebar.subheader("🏈 Admin Panel")
    
    # Instructions
    st.sidebar.markdown(
        "📌 **Admin Only:** Upload the updated season leaderboard JSON after the week ends.\n"
        "Make sure the file matches the manager names in the league."
    )
    
    
    # File uploader
    uploaded_file = st.sidebar.file_uploader(
        "Upload season_leaderboard.json", type="json", key="season_upload"
    )
    
    if uploaded_file:
        try:
            uploaded_json = json.load(uploaded_file)
            
            # Sanity check for missing managers
            missing_managers = [m for m in MANAGERS if m not in uploaded_json]
            if missing_managers:
                st.sidebar.warning(f"⚠️ Uploaded JSON missing managers: {missing_managers}")
            else:
                # Save uploaded JSON to server file
                with open(SEASON_FILE, "w") as f:
                    json.dump(uploaded_json, f, indent=2)
                
                st.sidebar.success("✅ Season leaderboard updated!")
                
                # Show top 3 managers for quick verification
                top3 = sorted(uploaded_json.items(), key=lambda x: x[1]['total_points'], reverse=True)[:3]
                st.sidebar.markdown("🏆 **Current Top 3:**")
                for i, (manager, stats) in enumerate(top3, start=1):
                    st.sidebar.markdown(f"{i}. {manager} — {stats['total_points']} pts")
                
                # Reload in app
                season = uploaded_json
        except Exception as e:
            st.sidebar.error(f"Failed to load JSON: {e}")




# ----------------------------
# Load latest CSV
# ----------------------------
latest_csv, current_week_key = load_latest_csv()
if not latest_csv:
    st.error(f"No CSV found in {SALARIES_FOLDER}. Drop the weekly FanDuel CSV there.")
    st.stop()

df = load_csv(latest_csv)
leaderboard = load_leaderboard()
submitted = current_week_key in leaderboard and username in leaderboard[current_week_key]

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
# Build Lineup
# ----------------------------
st.subheader("Build Your Lineup")
state_key = f"lineup_{username}_{current_week_key}"

if state_key not in st.session_state:
    st.session_state[state_key] = {}

lineup = st.session_state[state_key]
submitted_lineup = leaderboard.get(current_week_key, {}).get(username)
if submitted_lineup:
    st.info("You have already submitted a lineup. You cannot change it.")
    lineup_df = pd.DataFrame.from_dict(submitted_lineup, orient="index")
    st.dataframe(lineup_df)
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

            # Remove already selected players except current
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
# Weekly Leaderboard with cached live points
# ----------------------------
week_number = int(current_week_key.split("_week_")[1])

# Load cache
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        player_cache = json.load(f)
else:
    player_cache = {}

def get_player_points(player_id, season, week):
    cache_key = f"{player_id}_{season}_{week}"
    if cache_key in player_cache:
        return player_cache[cache_key]
    url = f"https://api.sleeper.app/v1/stats/nfl/player/{player_id}?season={season}&season_type=regular&week={week}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        points = response.json().get("fantasy_points", 0)
    except:
        points = 0
    player_cache[cache_key] = points
    with open(CACHE_FILE,"w") as f:
        json.dump(player_cache,f)
    return points

if submitted:
    st.subheader("🏆 Family Weekly Leaderboard")
    weekly_display = {}
    for manager, lineup_data in leaderboard[current_week_key].items():
        manager_scores = {}
        total_points = 0
        for slot, player in lineup_data.items():
            player_name = player["name"]
            player_id = mapping.get(player_name)
            points = get_player_points(player_id, SEASON_YEAR, week_number) if player_id else 0
            manager_scores[slot] = f"{player_name} ({points} FPPG)"
            total_points += points
        manager_scores["Total"] = total_points
        weekly_display[manager] = manager_scores
    st.dataframe(pd.DataFrame(weekly_display))

# ----------------------------
# Season Leaderboard
# ----------------------------
season = load_season()
st.subheader("📊 Season Leaderboard")
season_df = pd.DataFrame(season).T
season_df["Placement Points"] = (
    season_df["weeks_1st"]*10 +
    season_df["weeks_2nd"]*6 +
    season_df["weeks_3rd"]*3
)
season_df = season_df.sort_values(by=["Placement Points","total_points"], ascending=False)
st.dataframe(season_df)
