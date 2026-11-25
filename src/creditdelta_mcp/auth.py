import streamlit as st
from supabase import create_client


def get_user_client():
    # Never cache this globally: it holds one user's login session.
    if "supabase_client" not in st.session_state:
        st.session_state.supabase_client = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_PUBLISHABLE_KEY"],
        )
    return st.session_state.supabase_client


def show_account():
    """Render account controls. Return a server-verified user or None."""
    client = get_user_client()
    user = None

    if st.session_state.get("signed_in"):
        try:
            user = client.auth.get_user().user
        except Exception:
            st.warning("Could not verify your login. Please sign in again.")
            st.session_state.pop("supabase_client", None)
            st.session_state.pop("signed_in", None)
            client = get_user_client()

    if user:
        st.caption(f"Signed in: {user.email}")

        if st.button("Sign out", key="account_sign_out"):
            try:
                client.auth.sign_out()
            except Exception:
                pass
            # Clear drafts and pending UI state before another user signs in.
            st.session_state.clear()
            st.rerun()

        return user

    with st.expander("Sign in to My Reports"):
        st.caption("You can analyze and download reports without signing in.")

        with st.form("account_login", clear_on_submit=True):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")

        if submitted:
            if not email.strip() or not password:
                st.warning("Enter your email and password.")
            else:
                try:
                    response = client.auth.sign_in_with_password(
                        {"email": email.strip(), "password": password}
                    )
                    authenticated = bool(response.session)
                except Exception:
                    authenticated = False

                if authenticated:
                    st.session_state.clear()
                    st.session_state.supabase_client = client
                    st.session_state.signed_in = True
                    st.rerun()
                else:
                    st.error(
                        "Sign-in failed. Check your credentials and "
                        "email confirmation, or try again later."
                    )

    return None