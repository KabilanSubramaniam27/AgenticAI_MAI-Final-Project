"""Streamlit talks only to FastAPI; no model/provider/database credentials in the browser."""

import json
import uuid
from datetime import date, timedelta
from io import BytesIO

import httpx
import streamlit as st
from PIL import Image

from tripradar_agents.config import ROOT, Settings

# Local presentation assets never enter model context or destination evidence.
IMAGES = ROOT / "images"


def inspiration_assets():
    catalog = IMAGES / "catalog.json"
    if not catalog.is_file():
        return []
    return json.loads(catalog.read_text())


@st.cache_data(show_spinner=False)
def display_image(path, modified_ns):
    # Decode AVIF/WebP server-side for consistent browser support; originals stay intact.
    with Image.open(path) as source:
        output = BytesIO()
        source.save(output, format="PNG")
        return output.getvalue()


def local_image(filename, caption=None):
    path = IMAGES / filename
    if path.is_file():
        st.image(
            display_image(str(path), path.stat().st_mtime_ns), caption=caption, width="stretch"
        )


def welcome():
    st.markdown(
        """<style>
        .block-container {max-width: 1160px; padding-top: 2.4rem;}
        h1, h2, h3 {letter-spacing: -0.025em;}
        [data-testid="stImage"] img {border-radius: 16px;}
        [data-testid="stForm"] {border-radius: 18px; padding: 1.5rem;}
        div.stButton > button[kind="primary"],
        div.stFormSubmitButton > button[kind="primary"] {border-radius: 12px;}
        </style>""",
        unsafe_allow_html=True,
    )
    intro, visual = st.columns([1.05, 1], gap="large", vertical_alignment="center")
    with intro:
        st.caption("TRIPRADAR  /  A LITTLE PLANNING. MORE DISCOVERY.")
        st.title("Your next chapter starts here.")
        st.write(
            "Turn your dates, budget and curiosity into a trip built around you. "
            "Explore ideas backed by destination guides, with clear costs and weather context."
        )
        st.caption("LISBON · PARIS · LONDON · NEW YORK CITY")
    with visual:
        local_image("Title-Image.webp", "Start with a map. Make it your own.")
    with st.expander("A little travel inspiration", expanded=False):
        st.caption(
            "Illustrative images from the project’s image library, not destination evidence or live offers."
        )
        columns = st.columns(3)
        for index, asset in enumerate(inspiration_assets()):
            with columns[index % 3]:
                local_image(asset["filename"], asset["caption"])
    st.divider()


def show_http_rejection(exc):
    # Never echo arbitrary backend bodies: validation errors may contain submitted input.
    messages = {
        401: "Your session is not authorized. Start a new trip.",
        403: "Your session has expired or belongs to another backend. Start a new trip.",
        409: "A request is already active, or the message ID was reused with different input.",
        413: "The request is too large. Shorten the message.",
        422: "The request failed validation. Check dates, rooms, traveler counts and message content.",
        429: "The backend is busy. Wait for pending requests to finish, then retry.",
        503: "The backend is running but not ready. Check /ready for missing configuration and restart after updating .env.",
    }
    status = exc.response.status_code
    st.error(
        f"HTTP {status}: " + messages.get(status, "The backend could not process this request.")
    )


def main():
    st.set_page_config(
        page_title="TripRadar · Plan your next chapter", page_icon="🧳", layout="wide"
    )
    welcome()
    base = Settings().api_url

    def api(method, path, **kwargs):
        headers = {"Authorization": st.session_state.get("capability", "")}
        response = httpx.request(method, base + path, headers=headers, timeout=10, **kwargs)
        if path == "/ready" and response.status_code == 503:
            return response.json()
        response.raise_for_status()
        return response.json()

    try:
        health = api("GET", "/health")
        if health["environment"] == "fixture":
            st.warning(
                "Fixture mode: scripted model and synthetic prices/weather. Not a live trip quote."
            )
        readiness = api("GET", "/ready")
        ready = readiness.get("ready", True)
        if not ready:
            st.error("The backend is running, but live agent configuration is incomplete.")
            known_settings = {
                "OPENAI_API_KEY",
                "TRIPRADAR_AGENT_INPUT_USD_PER_MILLION",
                "TRIPRADAR_AGENT_OUTPUT_USD_PER_MILLION",
            }
            for name in readiness.get("missing_settings", []):
                if name in known_settings:
                    st.code(name)
            st.info(
                "Set the missing values in .env, then restart the backend. "
                "Token rates must be positive numbers from your provider's rate card. "
                "LangSmith credentials are separate from the selected LLM provider API key."
            )
        if "thread_id" not in st.session_state:
            st.session_state.update(api("POST", "/sessions"))
        if st.button("New trip"):
            api("DELETE", "/sessions/" + st.session_state.thread_id)
            st.session_state.pop("thread_id", None)
            st.session_state.pop("pending", None)
            st.session_state.pop("result", None)
            st.rerun()
        st.subheader("Make the trip yours")
        st.caption("Choose one city, set your dates and tell us what you would love to discover.")
        with st.form("trip"):
            destination = st.selectbox(
                "Destination", ["Lisbon", "Paris", "London", "New York City"]
            )
            dates = st.columns(3)
            with dates[0]:
                start = st.date_input("Start date", date.today() + timedelta(days=7))
            with dates[1]:
                outbound = st.date_input("Outbound flight date (origin local)", start)
            with dates[2]:
                end = st.date_input("End date", date.today() + timedelta(days=16))
            costs = st.columns(3)
            with costs[0]:
                amount = st.number_input("Total trip budget", min_value=1, value=2000)
            with costs[1]:
                currency = st.selectbox("Currency", ["USD", "EUR", "GBP"])
            with costs[2]:
                origin = st.selectbox(
                    "Exact departure airport", ["JFK", "EWR", "LHR", "LGW", "CDG", "ORY", "LIS"]
                )
            party = st.columns(2)
            with party[0]:
                adults = st.number_input("Adults", min_value=1, max_value=8, value=1)
            with party[1]:
                rooms = st.number_input("Rooms", min_value=1, max_value=4, value=1)
            message = st.text_area("Request / interests", "Please plan a trip using these details.")
            st.caption(
                "Optional allowances are whole-trip amounts for all travelers, in the selected currency. Leave unapproved costs unknown."
            )
            clear_allowances = st.checkbox("Clear previously accepted allowances", value=False)
            accept_allowances = st.checkbox("Use these explicit spending allowances", value=False)
            allowances = {
                category: st.number_input(label, min_value=0, value=0)
                for category, label in (
                    ("food", "Food allowance"),
                    ("local_transport", "Local and airport transport allowance"),
                    ("activities", "Activities allowance"),
                    ("mandatory_fees", "Unpriced mandatory fees allowance"),
                )
            }
            submitted = st.form_submit_button(
                "Build my trip", type="primary", disabled="pending" in st.session_state or not ready
            )
        if submitted:
            # Retain ID/payload across a network retry to avoid duplicate paid requests.
            payload = {
                "thread_id": st.session_state.thread_id,
                "client_message_id": uuid.uuid4().hex,
                "message": message,
                "allowances": allowances if accept_allowances else {},
                "clear_allowances": clear_allowances,
                "trip_fields": {
                    "destination": destination,
                    "start_date": str(start),
                    "outbound_date": str(outbound),
                    "end_date": str(end),
                    "budget": amount,
                    "currency": currency,
                    "origin": origin,
                    "adults": adults,
                    "rooms": rooms,
                },
            }
            st.session_state.submission = payload
            st.session_state.pending = api("POST", "/chat", json=payload)["request_id"]
        if "submission" in st.session_state and "pending" not in st.session_state:
            if st.button("Retry last submission", disabled=not ready):
                st.session_state.pending = api("POST", "/chat", json=st.session_state.submission)[
                    "request_id"
                ]

        @st.fragment(run_every="2s")
        def response_panel():
            try:
                if "pending" in st.session_state:
                    record = api("GET", "/requests/" + st.session_state.pending)
                    st.info("Request: " + record["status"])
                    if record["status"] in ("completed", "failed", "interrupted"):
                        st.session_state.result = record["result"]
                        del st.session_state.pending
                        st.session_state.pop("submission", None)
                        st.rerun()
                result = st.session_state.get("result")
                if result:
                    st.subheader("Your trip, day by day")
                    st.write(result["answer"])
                    for day in result.get("days", []):
                        st.subheader(day["date"])
                        for activity in day["activities"]:
                            st.write(activity["claim"])
                            st.caption("Source: " + activity["evidence_id"])
                        if not day["activities"]:
                            st.write("No supported activity selected for this day.")
                        st.caption("Weather: " + day["weather"])
                        if any(c.get("conflict") for c in day.get("conflicts", [])):
                            st.warning("Rain conflicts with a planned outdoor activity.")
                        if day["date"] in result.get("reconciliation", {}).get("travel_days", []):
                            st.info("Reserved for arrival/departure travel.")
                    if "budget" in result:
                        st.subheader("Budget")
                        if result["budget"].get("verdict_basis") == "test_data":
                            st.warning(
                                "Test/fixture prices: this does not establish a live trip cost."
                            )
                        ledger = result["budget"]
                        st.write(
                            "Known subtotal: "
                            + ledger.get("currency", "")
                            + " "
                            + str(ledger.get("known_subtotal") or "Unknown")
                        )
                        st.write("Full trip total: " + str(ledger.get("total") or "Unknown"))
                        if ledger.get("lines"):
                            st.dataframe(
                                [
                                    {
                                        "Category": line["category"].replace("_", " ").title(),
                                        "Amount": line["amount"],
                                        "Source": line["evidence_id"],
                                    }
                                    for line in ledger["lines"]
                                ],
                                hide_index=True,
                            )
                        with st.expander("Budget evidence and assumptions"):
                            st.json(ledger)
                    selected_ids = set(
                        result.get("reconciliation", {}).get("selected_offer_ids", [])
                    )
                    selected = [r for r in result.get("evidence", []) if r["id"] in selected_ids]
                    if selected:
                        with st.expander("Selected flight and hotel quotes"):
                            for offer in selected:
                                st.text(
                                    offer.get("hotel_name", offer.get("category", "Combined quote"))
                                )
                                st.write(offer.get("currency", ""), offer.get("amount", ""))
                                if offer.get("arrival"):
                                    st.write("Destination arrival:", offer["arrival"])
                                    st.write("Destination departure:", offer["departure"])
                                st.caption(
                                    "Pricing environment: "
                                    + offer.get(
                                        "provider_environment", offer.get("environment", "unknown")
                                    )
                                )
                    for limitation in result.get("limitations", []):
                        st.write(limitation)
                    with st.expander("Sources"):
                        for source in result.get("evidence", []):
                            st.write(source.get("id"))
                            st.write(source.get("url", source.get("reason", "")))
                            st.caption(
                                source.get("attribution", "") + " " + source.get("license", "")
                            )
            except httpx.HTTPStatusError as exc:
                show_http_rejection(exc)
            except httpx.RequestError:
                st.error(
                    "Could not reach the API. Your pending request ID is retained; polling will retry."
                )

        response_panel()
    except httpx.HTTPStatusError as exc:
        show_http_rejection(exc)
    except httpx.RequestError:
        st.error(
            "Cannot connect to the TripRadar backend. Start the launcher and check "
            "that FastAPI is listening on the configured API address."
        )


if __name__ == "__main__":
    main()
