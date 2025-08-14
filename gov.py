import streamlit as st
import json
import os
import hashlib
import requests
import pandas as pd
import altair as alt
from datetime import datetime
from groq import Groq


# -----------------------------
# CONFIG
# -----------------------------
USER_DB_FILE = "users.json"
API_KEY = "09eaed9b4b2493633488f8bfc3fd3f8d"  # <-- replace with your OpenWeather API key

# -----------------------------
# UTIL: password hash
# -----------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# -----------------------------
# USER DATA FUNCTIONS (with auto-upgrade)
# -----------------------------
def load_users():
    """Load users from JSON and auto-upgrade old string-hash format to dict format."""
    if not os.path.exists(USER_DB_FILE):
        with open(USER_DB_FILE, "w") as f:
            json.dump({}, f)
    with open(USER_DB_FILE, "r") as f:
        try:
            users = json.load(f)
        except json.JSONDecodeError:
            users = {}
    upgraded = False
    for uname, udata in list(users.items()):
        if isinstance(udata, str):
            # old format: username -> password_hash
            users[uname] = {"password": udata, "default_city": None}
            upgraded = True
        elif isinstance(udata, dict):
            # ensure keys exist
            if "password" not in udata:
                users[uname]["password"] = ""
                upgraded = True
            if "default_city" not in udata:
                users[uname]["default_city"] = None
                upgraded = True
    if upgraded:
        save_users(users)
    return users

def save_users(users: dict):
    with open(USER_DB_FILE, "w") as f:
        json.dump(users, f, indent=2)

# -----------------------------
# AUTH: signup & login (backwards compatible)
# -----------------------------
def signup():
    st.subheader("📝 Signup")
    new_username = st.text_input("Choose a username", key="signup_user")
    new_password = st.text_input("Choose a password", type="password", key="signup_pass")
    confirm_password = st.text_input("Confirm password", type="password", key="signup_confirm")

    if st.button("Create Account", key="signup_btn"):
        if not new_username:
            st.warning("Enter a username.")
            return
        if new_password != confirm_password:
            st.warning("Passwords do not match.")
            return
        users = load_users()
        if new_username in users:
            st.warning("Username already exists. Please pick another.")
            return
        users[new_username] = {"password": hash_password(new_password), "default_city": None}
        save_users(users)
        st.success("Account created! You can now log in.")

def login():
    st.subheader("🔐 Login")
    username = st.text_input("Username", key="login_user")
    password = st.text_input("Password", type="password", key="login_pass")
    if st.button("Login", key="login_btn"):
        if not username:
            st.error("Enter username.")
            return
        users = load_users()
        if username in users:
            user_data = users[username]
            # if old format string (should already be upgraded at load_users), handle anyway
            if isinstance(user_data, str):
                user_data = {"password": user_data, "default_city": None}
                users[username] = user_data
                save_users(users)
            if user_data.get("password") == hash_password(password):
                st.session_state["user"] = username
                # prefill city from profile if present
                if user_data.get("default_city"):
                    st.session_state["city"] = user_data.get("default_city")
                else:
                    st.session_state["city"] = ""
                st.success(f"Welcome, {username}!")
            else:
                st.error("Invalid credentials.")
        else:
            st.error("Invalid credentials.")

# -----------------------------
# WEATHER API helpers
# -----------------------------
def get_weather(city: str):
    """Current weather"""
    if not city:
        return None
    url = f"https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": API_KEY, "units": "metric"}
    resp = requests.get(url, params=params, timeout=8)
    if resp.status_code != 200:
        return None
    d = resp.json()
    return {
        "city_name": f"{d.get('name')}, {d.get('sys',{}).get('country','')}",
        "temp": d["main"]["temp"],
        "feels_like": d["main"].get("feels_like"),
        "humidity": d["main"]["humidity"],
        "condition_main": d["weather"][0]["main"],
        "condition_desc": d["weather"][0]["description"],
        "icon": d["weather"][0]["icon"]
    }

def get_forecast(city: str):
    """5-day / 3-hour forecast"""
    if not city:
        return None
    url = f"https://api.openweathermap.org/data/2.5/forecast"
    params = {"q": city, "appid": API_KEY, "units": "metric"}
    resp = requests.get(url, params=params, timeout=8)
    if resp.status_code != 200:
        return None
    data = resp.json()
    forecast_list = []
    for item in data.get("list", []):
        dt = datetime.fromtimestamp(item["dt"])
        temp = item["main"]["temp"]
        main = item["weather"][0]["main"]
        desc = item["weather"][0]["description"]
        icon = item["weather"][0]["icon"]
        forecast_list.append({
            "datetime": dt,
            "temp": temp,
            "main": main,
            "desc": desc,
            "icon": icon
        })
    return forecast_list

def get_city_from_ip():
    try:
        r = requests.get("https://ipinfo.io", timeout=6)
        if r.status_code == 200:
            data = r.json()
            return data.get("city")
    except:
        return None

# -----------------------------
# UX Helpers: categorize condition -> risk/color
# -----------------------------
def map_risk(cat: str):
    cat_l = (cat or "").lower()
    if "rain" in cat_l or "thunder" in cat_l or "drizzle" in cat_l:
        return "rain"
    if "clear" in cat_l:
        return "clear"
    if "cloud" in cat_l:
        return "clouds"
    if "snow" in cat_l:
        return "snow"
    return "other"

def risk_color_map():
    return {
        "rain": "#1f77b4",    # blue
        "clear": "#ff7f0e",   # orange
        "clouds": "#7f7f7f",  # gray
        "snow": "#17becf",    # teal
        "other": "#2ca02c"    # green
    }

# -----------------------------
# WEATHER UI (graph default, text option, icons, save default city)
# -----------------------------
def weather_alerts_ui():
    st.subheader("🌦️ Weather-Aware Smart Alerts")

    if "city" not in st.session_state:
        st.session_state["city"] = ""

    # Location detection button
    col1, col2 = st.columns([3,1])
    with col1:
        city_input = st.text_input("Enter your city name (or use the button):", value=st.session_state.get("city", ""))
    with col2:
        if st.button("📍 Use My Current Location"):
            detected = get_city_from_ip()
            if detected:
                st.session_state["city"] = detected
                city_input = detected
                st.success(f"Detected location: {detected}")
            else:
                st.error("Could not detect location from IP. Please enter manually.")

    city = city_input.strip()

    # Fetch action
    if st.button("Get Weather Info"):
        if not city:
            st.warning("Please enter or detect a city.")
            return

        # Fetch current weather + forecast
        with st.spinner("Fetching weather and forecast..."):
            current = get_weather(city)
            forecast = get_forecast(city)

        if current is None:
            st.error("❌ Could not fetch current weather. Check city name or API key.")
            return

        # Show current summary
        icon_url = f"https://openweathermap.org/img/wn/{current['icon']}@2x.png"
        c1, c2 = st.columns([1,4])
        with c1:
            st.image(icon_url, width=80)
        with c2:
            st.markdown(f"### {current['city_name']}")
            st.write(f"**🌡 Temperature:** {current['temp']} °C (Feels like {current.get('feels_like')}°C)")
            st.write(f"**💧 Humidity:** {current['humidity']}%")
            st.write(f"**☁️ Condition:** {current['condition_main']} — {current['condition_desc'].capitalize()}")

        # Smart quick advice
        cond = current['condition_main'].lower()
        if any(k in cond for k in ["rain", "thunder", "drizzle"]):
            st.warning("⚠️ Rain expected — avoid watering and delay foliar sprays.")
        elif current['temp'] > 35:
            st.warning("🔥 High heat — consider mulching and watering early morning.")
        elif current['humidity'] < 30:
            st.warning("💨 Dry air — water early morning/evening.")
        else:
            st.success("✅ Conditions look normal for routine farm activities.")

        # Offer to save as default
        users = load_users()
        username = st.session_state.get("user")
        if username:
            if st.checkbox("Save this city as my default"):
                users[username]["default_city"] = city
                save_users(users)
                st.info(f"Saved {city} as your default city.")

        # Forecast display (graph default)
        if forecast:
            st.subheader("📅 5-Day Forecast (3-hour steps)")
            # Build DataFrame
            df = pd.DataFrame(forecast)
            if df.empty:
                st.warning("No forecast entries available.")
            else:
                # Create risk column and color mapping
                df["risk"] = df["main"].apply(map_risk)
                color_map = risk_color_map()

                # Prepare chart (Altair)
                chart_df = df[["datetime", "temp", "risk"]].copy()
                # Altair expects datetime type
                chart_df["datetime"] = pd.to_datetime(chart_df["datetime"])

                # Base line chart
                line = alt.Chart(chart_df).mark_line(point=True).encode(
                    x=alt.X("datetime:T", title="Date / Time"),
                    y=alt.Y("temp:Q", title="Temperature (°C)"),
                    color=alt.Color("risk:N", scale=alt.Scale(domain=list(color_map.keys()), range=list(color_map.values())), legend=alt.Legend(title="Weather type")),
                    tooltip=[alt.Tooltip("datetime:T", title="Date/Time"), alt.Tooltip("temp:Q", title="Temp (°C)"), alt.Tooltip("risk:N", title="Type")]
                ).properties(width=700, height=300)

                st.altair_chart(line, use_container_width=True)

                # Default view Graph first, allow switching to text
                view = st.radio("Forecast view:", ["Graph View", "Text List"], index=0)
                if view == "Text List":
                    st.markdown("### Forecast details")
                    # Show icon + time + temp + desc
                    for idx, row in df.iterrows():
                        icon_url = f"https://openweathermap.org/img/wn/{row['icon']}@2x.png"
                        cols = st.columns([0.2, 1, 1])
                        with cols[0]:
                            st.image(icon_url, width=48)
                        with cols[1]:
                            st.write(f"**{row['datetime'].strftime('%Y-%m-%d %H:%M')}**")
                        with cols[2]:
                            st.write(f"🌡 {row['temp']}°C — {row['desc'].capitalize()} — ({row['main']})")
        else:
            st.warning("Forecast data unavailable for this city (API limit or city error).")

# -----------------------------
# MAIN APP
# -----------------------------

# -----------------------------
# FORUM FUNCTIONS

# -----------------------------
# FORUM FUNCTIONS (with photo upload)
# -----------------------------
FORUM_DB_FILE = "forum.json"
IMAGE_DIR = "forum_images"
os.makedirs(IMAGE_DIR, exist_ok=True)

def load_forum():
    """Load forum data safely, reset if file is corrupted."""
    if not os.path.exists(FORUM_DB_FILE):
        with open(FORUM_DB_FILE, "w") as f:
            json.dump({"posts": []}, f)

    try:
        with open(FORUM_DB_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        st.warning("⚠ Forum data was corrupted. Resetting to empty.")
        with open(FORUM_DB_FILE, "w") as f:
            json.dump({"posts": []}, f)
        return {"posts": []}

def save_forum(data):
    with open(FORUM_DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

def save_image_file(uploaded_file):
    """Save uploaded image to local folder and return filename."""
    if uploaded_file:
        ext = uploaded_file.name.split(".")[-1]
        filename = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}.{ext}"
        filepath = os.path.join(IMAGE_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(uploaded_file.getvalue())
        return filename
    return None

def discussion_forum_ui():
    st.subheader("👨‍🌾 Farmer Discussion Forum")
    forum_data = load_forum()

    st.markdown("### 📢 Join the Forum")
    if st.checkbox("I agree to participate respectfully and help fellow farmers."):
        st.session_state["joined_forum"] = True

    if not st.session_state.get("joined_forum"):
        st.info("Please agree above to participate in the discussion forum.")
        return

    st.markdown("### 📝 Ask a Question")
    question = st.text_input("Enter your question")
    tag = st.selectbox("Select a tag", ["General", "Pest", "Irrigation", "Weather", "Soil", "Harvest"])
    q_image = st.file_uploader("Upload an image for your question (optional)", type=["jpg", "jpeg", "png"])

    if st.button("Post Question"):
        if question:
            image_filename = save_image_file(q_image)
            forum_data["posts"].append({
                "user": st.session_state["user"],
                "question": question,
                "tag": tag,
                "timestamp": datetime.now().isoformat(),
                "image": image_filename,
                "replies": []
            })
            save_forum(forum_data)
            st.success("Question posted!")
            st.rerun()

    st.markdown("---")
    st.markdown("### 💬 Questions and Replies")

    sort_option = st.radio("Sort questions by", ["Latest", "Most Replies"], horizontal=True)
    if sort_option == "Latest":
        sorted_posts = sorted(forum_data["posts"], key=lambda x: x["timestamp"], reverse=True)
    else:
        sorted_posts = sorted(forum_data["posts"], key=lambda x: len(x["replies"]), reverse=True)

    for i, post in enumerate(sorted_posts):
        st.markdown(f"**Q{i+1}. {post['question']}** — _by {post['user']}_ 🏷️ *{post['tag']}*")
        if post.get("image"):
            img_path = os.path.join(IMAGE_DIR, post["image"])
            if os.path.exists(img_path):
                st.image(img_path, width=300)

        for reply in post["replies"]:
            st.markdown(f"> 💬 {reply['reply']} — _{reply['user']}_")
            if reply.get("image"):
                img_path = os.path.join(IMAGE_DIR, reply["image"])
                if os.path.exists(img_path):
                    st.image(img_path, width=250)

        with st.expander("Reply"):
            reply_text = st.text_input(f"Your reply to Q{i+1}", key=f"reply_{i}")
            r_image = st.file_uploader(
                f"Upload an image for your reply (optional) to Q{i+1}",
                type=["jpg", "jpeg", "png"],
                key=f"reply_img_{i}"
            )
            if st.button("Submit Reply", key=f"reply_btn_{i}"):
                if reply_text:
                    image_filename = save_image_file(r_image)
                    post["replies"].append({
                        "user": st.session_state["user"],
                        "reply": reply_text,
                        "image": image_filename,
                        "timestamp": datetime.now().isoformat()
                    })
                    save_forum(forum_data)
                    st.success("Reply added!")
                    st.rerun()
def government_schemes_ui():
    st.subheader("🏛 Government Schemes for Farmers")

    # Static schemes list
    schemes = [
        {
            "name": "Pradhan Mantri Fasal Bima Yojana (PMFBY)",
            "description": "Provides crop insurance to farmers against natural calamities, pests, and diseases.",
            "eligibility": "All farmers growing notified crops in notified areas, including sharecroppers and tenant farmers.",
            "link": "https://pmfby.gov.in/"
        },
        {
            "name": "Kisan Credit Card (KCC)",
            "description": "Offers short-term credit to farmers for crop production needs at low interest rates.",
            "eligibility": "All farmers (individuals or joint) who own or cultivate land.",
            "link": "https://www.myscheme.gov.in/schemes/kcc"
        },
        {
            "name": "Soil Health Card Scheme",
            "description": "Provides soil health cards to farmers with crop-wise recommendations for nutrients and fertilizers.",
            "eligibility": "All farmers across India.",
            "link": "https://soilhealth.dac.gov.in/"
        },
        {
            "name": "Paramparagat Krishi Vikas Yojana (PKVY)",
            "description": "Promotes organic farming through cluster-based approach and certification.",
            "eligibility": "Groups of farmers or Farmer Producer Organizations.",
            "link": "https://pgsindia-ncof.gov.in/"
        },
        {
            "name": "Pradhan Mantri Krishi Sinchayee Yojana (PMKSY)",
            "description": "Aims to improve irrigation coverage and water efficiency.",
            "eligibility": "All farmers, with priority to small and marginal farmers.",
            "link": "https://pmksy.gov.in/"
        }
    ]

    # Display schemes
    for scheme in schemes:
        with st.expander(f"📌 {scheme['name']}"):
            st.write(f"**Description:** {scheme['description']}")
            st.write(f"**Eligibility:** {scheme['eligibility']}")
            st.markdown(f"[🔗 More Info / Apply Here]({scheme['link']})")

def farmer_chatbot_ui():
    st.subheader("🤖 Farmer's Assistant Chatbot ")
    st.markdown("🌾Smart advice for smarter farming — just type your question!")

    # Initialize Groq client
    client = Groq(api_key="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")  # Replace with your Groq API key

    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = [
            {"role": "system", "content": "You are a helpful assistant for farmers. Give short, simple advice in easy language."}
        ]

    # Input box
    user_input = st.text_input("💬 Ask your farming question:")

    if st.button("Send Question") and user_input:
        st.session_state["chat_messages"].append({"role": "user", "content": user_input})

        with st.spinner("Thinking..."):
            response = client.chat.completions.create(
                model="llama3-8b-8192",
                messages=st.session_state["chat_messages"]
            )
            reply = response.choices[0].message.content
            st.session_state["chat_messages"].append({"role": "assistant", "content": reply})

    # Show chat history
    for msg in st.session_state["chat_messages"]:
        if msg["role"] == "user":
            st.markdown(f"**👨‍🌾 You:** {msg['content']}")
        elif msg["role"] == "assistant":
            st.markdown(f"**🤖 Bot:** {msg['content']}")



def main():
    st.title("🌾 CROPCARE - Smart Farming Assistant")

    menu = ["Login", "Signup", "Weather Alerts", "Discussion Forum","Government Schemes","Farmer's Chatbot"]
    choice = st.sidebar.selectbox("Choose", menu)

    if choice == "Login":
        if "user" not in st.session_state:
            login()
        else:
            st.success(f"You're logged in as {st.session_state['user']}")
            # show quick link to weather after login
            if st.button("Go to Weather Alerts"):
                st.experimental_rerun()
    elif choice == "Signup":
        signup()
    elif choice == "Discussion Forum":
        if "user" in st.session_state:
            discussion_forum_ui()
        else:
            st.warning("Please login to access the discussion forum.")
    elif choice == "Weather Alerts":
        if "user" in st.session_state:
            # prefill city from profile if available
            users = load_users()
            username = st.session_state.get("user")
            if username and users.get(username, {}).get("default_city"):
                st.session_state["city"] = users[username]["default_city"]
            weather_alerts_ui()
        else:
            st.warning("Please login first to access Weather Alerts.")
    elif choice == "Government Schemes":
       if "user" in st.session_state:
          government_schemes_ui()
       else:
          st.warning("Please login to view government schemes.")

    elif choice == "Farmer's Chatbot":
        if "user" in st.session_state:
           farmer_chatbot_ui()
        else:
           st.warning("Please login to access the chatbot.")


if __name__ == "__main__":
    main()
