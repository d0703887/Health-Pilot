import json
import os
import streamlit as st
import requests

BASE = "http://127.0.0.1:8800"
USERS_CACHE = os.path.join(os.path.dirname(__file__), "users_cache.json")


# ── User cache (persists across sessions) ─────────────────────────────────

def load_cache() -> dict:
    """Returns {display_name: user_id} from the local cache file."""
    if os.path.exists(USERS_CACHE):
        with open(USERS_CACHE) as f:
            return json.load(f)
    return {}


def save_to_cache(name: str, user_id: str):
    cache = load_cache()
    cache[name] = user_id
    with open(USERS_CACHE, "w") as f:
        json.dump(cache, f, indent=2)


def remove_from_cache(name: str):
    cache = load_cache()
    cache.pop(name, None)
    with open(USERS_CACHE, "w") as f:
        json.dump(cache, f, indent=2)


# ── API helper ─────────────────────────────────────────────────────────────

def api(method: str, path: str, **kwargs):
    """Thin wrapper around requests. Returns (status_code, body)."""
    r = getattr(requests, method)(f"{BASE}{path}", **kwargs)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


def require_user():
    """Returns True if a user is loaded, otherwise shows a warning and returns False."""
    if not st.session_state.get("user_id"):
        st.warning("No user loaded. Go to **Profile** and create or load a user first.")
        return False
    return True


# ── Session state defaults ─────────────────────────────────────────────────

def init_state():
    defaults = {
        "user_id": "",
        "user_name": "",
        "chat_history": [],
        "thread_id": None,
        "interrupts": None,
        "pending_resume": None,   # {"thread_id": ..., "answers": ...}
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _login(user_id: str, user_name: str):
    st.session_state["user_id"] = user_id
    st.session_state["user_name"] = user_name
    st.session_state["chat_history"] = []
    st.session_state["thread_id"] = None
    st.session_state["interrupts"] = None


def _logout():
    st.session_state["user_id"] = ""
    st.session_state["user_name"] = ""
    st.session_state["chat_history"] = []
    st.session_state["thread_id"] = None
    st.session_state["interrupts"] = None
    st.session_state["pending_resume"] = None


# ── Page: Profile ──────────────────────────────────────────────────────────

def page_profile():
    st.title("Profile")

    if not st.session_state["user_id"]:
        cache = load_cache()

        tab_existing, tab_new = st.tabs(["Load existing user", "Create new user"])

        # ── Load existing user ──
        with tab_existing:
            if cache:
                selected = st.selectbox("Select user", list(cache.keys()))
                col1, col2 = st.columns([3, 1])
                if col1.button("Load", use_container_width=True):
                    uid = cache[selected]
                    status, body = api("get", f"/api/v1/users/{uid}")
                    if status == 200:
                        _login(body["id"], body["name"])
                        st.rerun()
                    else:
                        st.error("User not found on server — they may have been deleted.")
                        remove_from_cache(selected)
                        st.rerun()
                if col2.button("Forget", use_container_width=True, type="secondary", help="Remove from local list"):
                    remove_from_cache(selected)
                    st.rerun()
            else:
                st.info("No saved users yet. Create one in the next tab.")

        # ── Create new user ──
        with tab_new:
            with st.form("create_user_form"):
                name       = st.text_input("Name")
                col1, col2 = st.columns(2)
                age        = col1.number_input("Age", min_value=10, max_value=120, value=25)
                gender     = col2.selectbox("Gender", ["male", "female", "other", "prefer not to say"])
                col3, col4 = st.columns(2)
                height     = col3.number_input("Height (cm)", min_value=100.0, max_value=250.0, value=170.0)
                weight     = col4.number_input("Weight (kg)", min_value=30.0, max_value=300.0, value=70.0)
                submitted  = st.form_submit_button("Create user", use_container_width=True)

            if submitted:
                if not name:
                    st.error("Name is required.")
                else:
                    status, body = api("post", "/api/v1/users/", json={
                        "name": name, "age": int(age), "gender": gender,
                        "height_cm": height, "weight_kg": weight
                    })
                    if status == 201:
                        save_to_cache(body["name"], body["id"])
                        _login(body["id"], body["name"])
                        st.success(f"Created and saved!")
                        st.rerun()
                    else:
                        st.error("Failed to create user.")
        return

    # ── Current user panel ──
    uid = st.session_state["user_id"]
    st.subheader(f"{st.session_state['user_name']}")
    st.caption(f"ID: `{uid}`")

    _, body = api("get", f"/api/v1/users/{uid}")
    goals = body.get("goals", [])

    st.divider()
    st.markdown("**Active goals**")
    if goals:
        for g in goals:
            col1, col2 = st.columns([5, 1])
            col1.markdown(f"- **{g['goal_type']}** — {g['description']} _(by {g['target_date'] or 'no date'})_")
            if col2.button("Delete", key=f"del_goal_{g['id']}"):
                api("delete", f"/api/v1/users/{uid}/goals/{g['id']}")
                st.rerun()
    else:
        st.info("No active goals.")

    st.markdown("**Add a goal**")
    with st.form("add_goal_form"):
        goal_type   = st.selectbox("Type", ["muscle_gain", "weight_loss", "maintenance", "endurance", "flexibility", "other"])
        description = st.text_area("Description", placeholder="e.g. Gain 3kg of muscle in 12 weeks")
        target_date = st.date_input("Target date (optional)", value=None)
        if st.form_submit_button("Add goal", use_container_width=True):
            payload = {"goal_type": goal_type, "description": description}
            if target_date:
                payload["target_date"] = str(target_date)
            status, _ = api("post", f"/api/v1/users/{uid}/goals", json=payload)
            if status == 201:
                st.success("Goal added.")
                st.rerun()
            else:
                st.error("Failed to add goal.")

    st.divider()
    if st.button("Switch user", type="secondary"):
        _logout()
        st.rerun()


# ── Page: Chat ─────────────────────────────────────────────────────────────

def page_chat():
    st.title("Chat")

    if not require_user():
        return

    uid = st.session_state["user_id"]

    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── Phase 2: clarification was submitted last run — call API now ──
    if st.session_state["pending_resume"]:
        pending = st.session_state["pending_resume"]
        st.session_state["pending_resume"] = None
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                status, result = api("post", "/api/v1/chat/resume", json={
                    "thread_id": pending["thread_id"],
                    "answers": pending["answers"]
                })
            if status == 200:
                _handle_chat_result(result)
            else:
                st.error("Failed to resume conversation.")

    # ── Clarification UI ──
    if st.session_state["interrupts"]:
        st.divider()
        st.markdown("**The assistant needs a bit more information:**")
        answers = {}
        with st.form("clarification_form"):
            for interrupt in st.session_state["interrupts"]:
                per_question = {}
                for q in interrupt["questions"]:
                    options      = q["options"]
                    option_map   = {opt["label"]: opt["id"] for opt in options}
                    chosen_label = st.radio(q["question"], list(option_map.keys()), key=q["id"])
                    per_question[q["question"]] = option_map[chosen_label]
                answers[interrupt["id"]] = per_question
            # Phase 1: save answers, clear the form immediately, rerun
            if st.form_submit_button("Submit answers", use_container_width=True):
                st.session_state["pending_resume"] = {
                    "thread_id": st.session_state["thread_id"],
                    "answers": answers
                }
                st.session_state["interrupts"] = None
                st.session_state["thread_id"] = None
                st.rerun()
        return

    # ── Normal chat input ──
    query = st.chat_input("Ask about your health...")
    if query:
        st.session_state["chat_history"].append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                status, result = api("post", "/api/v1/chat/", json={
                    "user_id": uid,
                    "user_query": query
                })
            if status == 200:
                _handle_chat_result(result)
            elif status == 404:
                st.error("User not found. Please go to Profile and reload.")
            else:
                st.error("Something went wrong. Check the server logs.")

    if st.session_state["chat_history"]:
        if st.button("Clear chat", type="secondary"):
            st.session_state["chat_history"] = []
            st.session_state["thread_id"] = None
            st.session_state["interrupts"] = None
            st.rerun()


def _handle_chat_result(result: dict):
    if result["type"] == "answer":
        answer = result["answer"]
        st.markdown(answer)
        st.session_state["chat_history"].append({"role": "assistant", "content": answer})
        st.session_state["thread_id"] = None
        st.session_state["interrupts"] = None
    elif result["type"] == "clarification":
        st.session_state["thread_id"] = result["thread_id"]
        st.session_state["interrupts"] = result["interrupts"]
        st.info("Clarification needed — see below.")
        st.rerun()


# ── Page: Data ─────────────────────────────────────────────────────────────

def page_data():
    st.title("Logged Data")

    if not require_user():
        return

    uid = st.session_state["user_id"]
    tab_nutrition, tab_workouts, tab_sleep = st.tabs(["Nutrition", "Workouts", "Sleep"])

    with tab_nutrition:
        _, records = api("get", f"/api/v1/users/{uid}/nutrition")
        if not records:
            st.info("No nutrition records yet.")
        else:
            for r in sorted(records, key=lambda x: x["timestamp"], reverse=True):
                with st.expander(f"{r['timestamp'][:16]}  •  {r['food_name']}  ({r['calories']} kcal)"):
                    with st.form(f"edit_nutrition_{r['id']}"):
                        col1, col2 = st.columns(2)
                        food_name = col1.text_input("Food name", value=r["food_name"])
                        meal_type = col2.selectbox("Meal type",
                                                   ["Breakfast", "Lunch", "Dinner", "Snack", ""],
                                                   index=["Breakfast", "Lunch", "Dinner", "Snack", ""].index(r["meal_type"] or ""))
                        col3, col4, col5, col6 = st.columns(4)
                        calories = col3.number_input("Calories", value=r["calories"])
                        protein  = col4.number_input("Protein (g)", value=float(r["protein_g"]))
                        carbs    = col5.number_input("Carbs (g)", value=float(r["carbs_g"]))
                        fats     = col6.number_input("Fats (g)", value=float(r["fats_g"]))
                        col_save, col_del = st.columns([3, 1])
                        save   = col_save.form_submit_button("Save changes")
                        delete = col_del.form_submit_button("Delete", type="secondary")
                    if save:
                        api("patch", f"/api/v1/users/{uid}/nutrition/{r['id']}", json={
                            "food_name": food_name, "meal_type": meal_type or None,
                            "calories": int(calories), "protein_g": protein,
                            "carbs_g": carbs, "fats_g": fats
                        })
                        st.success("Saved.")
                        st.rerun()
                    if delete:
                        api("delete", f"/api/v1/users/{uid}/nutrition/{r['id']}")
                        st.rerun()

    with tab_workouts:
        _, records = api("get", f"/api/v1/users/{uid}/workouts")
        if not records:
            st.info("No workout records yet.")
        else:
            for r in sorted(records, key=lambda x: x["timestamp"], reverse=True):
                with st.expander(f"{r['timestamp'][:16]}  •  {r['activity_type']}  ({r['duration_minutes']} min)"):
                    with st.form(f"edit_workout_{r['id']}"):
                        col1, col2, col3 = st.columns(3)
                        activity  = col1.text_input("Activity type", value=r["activity_type"])
                        duration  = col2.number_input("Duration (min)", value=r["duration_minutes"])
                        intensity = col3.selectbox("Intensity",
                                                   ["Low", "Moderate", "High", ""],
                                                   index=["Low", "Moderate", "High", ""].index(r["intensity"] or ""))
                        notes = st.text_area("Notes", value=r["notes"] or "")
                        col_save, col_del = st.columns([3, 1])
                        save   = col_save.form_submit_button("Save changes")
                        delete = col_del.form_submit_button("Delete", type="secondary")
                    if save:
                        api("patch", f"/api/v1/users/{uid}/workouts/{r['id']}", json={
                            "activity_type": activity, "duration_minutes": int(duration),
                            "intensity": intensity or None, "notes": notes or None
                        })
                        st.success("Saved.")
                        st.rerun()
                    if delete:
                        api("delete", f"/api/v1/users/{uid}/workouts/{r['id']}")
                        st.rerun()

    with tab_sleep:
        _, records = api("get", f"/api/v1/users/{uid}/sleep")
        if not records:
            st.info("No sleep records yet.")
        else:
            for r in sorted(records, key=lambda x: x["date"], reverse=True):
                with st.expander(f"{r['date']}  •  {r['duration_hours']}h  (quality: {r['quality_score'] or '—'})"):
                    with st.form(f"edit_sleep_{r['id']}"):
                        col1, col2, col3 = st.columns(3)
                        date     = col1.date_input("Date", value=r["date"])
                        duration = col2.number_input("Duration (hours)", value=float(r["duration_hours"]), step=0.5)
                        quality  = col3.number_input("Quality score (0–100)", min_value=0, max_value=100,
                                                     value=r["quality_score"] or 0)
                        col_save, col_del = st.columns([3, 1])
                        save   = col_save.form_submit_button("Save changes")
                        delete = col_del.form_submit_button("Delete", type="secondary")
                    if save:
                        api("patch", f"/api/v1/users/{uid}/sleep/{r['id']}", json={
                            "date": str(date), "duration_hours": duration,
                            "quality_score": int(quality) if quality else None
                        })
                        st.success("Saved.")
                        st.rerun()
                    if delete:
                        api("delete", f"/api/v1/users/{uid}/sleep/{r['id']}")
                        st.rerun()


# ── App shell ──────────────────────────────────────────────────────────────

init_state()

st.set_page_config(page_title="HealthAgent", page_icon="💪", layout="wide")

with st.sidebar:
    st.title("💪 HealthAgent")
    if st.session_state["user_id"]:
        st.success(f"**{st.session_state['user_name']}**")
    else:
        st.info("No user loaded")
    st.divider()
    page = st.radio("Navigate", ["Profile", "Chat", "Data"], label_visibility="collapsed")

if page == "Profile":
    page_profile()
elif page == "Chat":
    page_chat()
elif page == "Data":
    page_data()